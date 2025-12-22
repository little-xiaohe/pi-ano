# src/hardware/input/ir_input.py

from dataclasses import dataclass
from typing import List, Optional

import time
import board
import busio
import digitalio
import adafruit_vl53l0x

from src.logic.input_event import InputEvent, EventType
from src.hardware.config.keys import KeyId


@dataclass
class IRSensorChannel:
    sensor: adafruit_vl53l0x.VL53L0X
    key: KeyId
    on_threshold_mm: int
    off_threshold_mm: int
    last_present: bool = False
    raw_present: bool = False
    on_count: int = 0
    off_count: int = 0
    last_change_time: float = 0.0


class IRInput:
    """
    Multi-sensor IR input system using VL53L0X time-of-flight sensors.

    Continuous mode:
        - Each sensor continuously performs ranging in the background.
        - poll() reads the latest available range value.

    Notes:
        - Larger timing budget => more stable readings but slower updates.
        - Typical values: 50_000 (50ms), 100_000 (100ms), 200_000 (200ms)
    """

    def __init__(
        self,
        on_threshold_mm: int = 180,
        off_threshold_mm: int = 240,
        debug: bool = False,
        default_velocity: float = 1.0,
        cooldown_sec: float = 0.05,
        on_stable_frames: int = 1,
        off_stable_frames: int = 1,
        timing_budget_us: int = 50_000,         
        start_continuous: bool = True,
        power_on_delay_s: float = 0.15,
    ) -> None:
        self.debug = debug
        self.on_threshold_mm = on_threshold_mm
        self.off_threshold_mm = off_threshold_mm
        self.default_velocity = max(0.0, min(1.0, default_velocity))
        self.cooldown_sec = cooldown_sec
        self.on_stable_frames = on_stable_frames
        self.off_stable_frames = off_stable_frames

        self.timing_budget_us = int(timing_budget_us)
        self.start_continuous = bool(start_continuous)
        self.power_on_delay_s = float(power_on_delay_s)
        self.signal_rate_limit = 0.5

        # Keep references so sensors won't get GC'd and so we can stop continuous later
        self._sensors: List[adafruit_vl53l0x.VL53L0X] = []

        # -------------------------------------------------------------------
        # Shared I2C bus
        # -------------------------------------------------------------------
        i2c = busio.I2C(board.SCL, board.SDA)

        # -------------------------------------------------------------------
        # XSHUT pins / key map / addresses
        # -------------------------------------------------------------------
        xshut_pins = [
            board.D21,  # Sensor 0 → KEY_0
            board.D20,  # Sensor 1 → KEY_1
            board.D16,  # Sensor 2 → KEY_2
            board.D26,  # Sensor 3 → KEY_3
            board.D12,  # Sensor 4 → KEY_4
        ]

        key_map = [
            KeyId.KEY_0,
            KeyId.KEY_1,
            KeyId.KEY_2,
            KeyId.KEY_3,
            KeyId.KEY_4,
        ]

        addresses = [0x30, 0x31, 0x32, 0x33, 0x34]

        if len(xshut_pins) != len(key_map) or len(key_map) != len(addresses):
            raise ValueError("xshut_pins, key_map, and addresses must match in length")

        # -------------------------------------------------------------------
        # Step 1: Force all sensors into shutdown
        # -------------------------------------------------------------------
        xshut_ios: List[digitalio.DigitalInOut] = []
        for pin in xshut_pins:
            dio = digitalio.DigitalInOut(pin)
            dio.direction = digitalio.Direction.OUTPUT
            dio.value = False  # LOW = shutdown
            xshut_ios.append(dio)

        time.sleep(0.10)

        # -------------------------------------------------------------------
        # Step 2: Bring sensors up one at a time and assign new address
        #         Then configure timing budget and start continuous mode.
        # -------------------------------------------------------------------
        sensors: List[adafruit_vl53l0x.VL53L0X] = []

        for idx, (dio, new_addr) in enumerate(zip(xshut_ios, addresses)):
            dio.value = True
            time.sleep(self.power_on_delay_s)

            sensor = adafruit_vl53l0x.VL53L0X(i2c)
            sensor.set_address(new_addr)

            # Configure timing budget (microseconds)
            # NOTE: 33_000us = 33ms, 200_000us = 200ms
            try:
                sensor.measurement_timing_budget = self.timing_budget_us
                sensor.signal_rate_limit = self.signal_rate_limit
            except Exception as e:
                if self.debug:
                    print(f"[IR] Failed to set timing budget on sensor {idx}: {e}")

            # Start continuous mode (optional)
            if self.start_continuous:
                try:
                    sensor.start_continuous()
                except Exception as e:
                    if self.debug:
                        print(f"[IR] Failed to start continuous on sensor {idx}: {e}")

            if self.debug:
                print(
                    f"[IR] Sensor {idx} addr=0x{new_addr:02X} "
                    f"timing_budget={self.timing_budget_us}us "
                    f"continuous={'ON' if self.start_continuous else 'OFF'}"
                )

            sensors.append(sensor)

        self._sensors = sensors

        # -------------------------------------------------------------------
        # Step 3: Build channel list
        # -------------------------------------------------------------------
        self.channels: List[IRSensorChannel] = []
        now = time.monotonic()
        for sensor, key in zip(sensors, key_map):
            self.channels.append(
                IRSensorChannel(
                    sensor=sensor,
                    key=key,
                    on_threshold_mm=self.on_threshold_mm,
                    off_threshold_mm=self.off_threshold_mm,
                    last_present=False,
                    raw_present=False,
                    on_count=0,
                    off_count=0,
                    last_change_time=now,
                )
            )

    def close(self) -> None:
        """Optional cleanup: stop continuous ranging."""
        if not self.start_continuous:
            return
        for s in self._sensors:
            try:
                s.stop_continuous()
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Poll sensors and produce NOTE_ON / NOTE_OFF events
    # -----------------------------------------------------------------------
    def poll(self) -> List[InputEvent]:
        events: List[InputEvent] = []
        now = time.monotonic()

        for ch in self.channels:
            try:
                distance = ch.sensor.range
            except OSError:
                if self.debug:
                    print(f"[IR] Read error on key={ch.key}")
                continue

            # Hysteresis on raw_present
            if not ch.raw_present:
                raw_present = distance < ch.on_threshold_mm
            else:
                raw_present = distance < ch.off_threshold_mm

            ch.raw_present = raw_present

            # Debounce counters
            if raw_present:
                ch.on_count += 1
                ch.off_count = 0
            else:
                ch.off_count += 1
                ch.on_count = 0

            debounced_present = ch.last_present

            # OFF → ON
            if not ch.last_present:
                if ch.on_count >= self.on_stable_frames:
                    if (now - ch.last_change_time) >= self.cooldown_sec:
                        debounced_present = True
                        ch.last_change_time = now
                        if self.debug:
                            print(
                                f"[IR] key={int(ch.key)} DEBOUNCED ON "
                                f"(dist={distance}mm, on_count={ch.on_count})"
                            )
                    else:
                        if self.debug:
                            print(
                                f"[IR] key={int(ch.key)} OFF→ON suppressed by cooldown "
                                f"(dt={now - ch.last_change_time:.3f}s)"
                            )
            # ON → OFF
            else:
                if ch.off_count >= self.off_stable_frames:
                    debounced_present = False
                    ch.last_change_time = now
                    if self.debug:
                        print(
                            f"[IR] key={int(ch.key)} DEBOUNCED OFF "
                            f"(dist={distance}mm, off_count={ch.off_count})"
                        )

            # Emit events on debounced edge
            if debounced_present != ch.last_present:
                if debounced_present:
                    velocity = self.default_velocity
                    events.append(
                        InputEvent(
                            type=EventType.NOTE_ON,
                            key=ch.key,
                            velocity=velocity,
                            source="ir",
                        )
                    )
                    if self.debug:
                        print(
                            f"[IR] NOTE_ON key={ch.key} dist={distance}mm vel={velocity:.2f}"
                        )
                else:
                    events.append(
                        InputEvent(
                            type=EventType.NOTE_OFF,
                            key=ch.key,
                            source="ir",
                        )
                    )
                    if self.debug:
                        print(f"[IR] NOTE_OFF key={ch.key}")

            if self.debug:
                print(
                    f"[IR] key={int(ch.key)} dist={distance}mm "
                    f"raw_present={raw_present} "
                    f"on_count={ch.on_count} off_count={ch.off_count} "
                    f"debounced={debounced_present}"
                )

            ch.last_present = debounced_present

        return events
