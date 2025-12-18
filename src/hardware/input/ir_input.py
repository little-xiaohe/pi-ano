# src/hardware/input/ir_input.py

from dataclasses import dataclass
from typing import List

import time
import board
import busio
import digitalio
import adafruit_vl53l0x

from src.logic.input_event import InputEvent, EventType
from src.hardware.config.keys import KeyId


# ---------------------------------------------------------------------------
# IRSensorChannel
# ---------------------------------------------------------------------------

@dataclass
class IRSensorChannel:
    """
    Represents a single VL53L0X distance sensor mapped to a logical key.

    Attributes:
        sensor: The VL53L0X sensor instance.
        key: Logical key assigned to this sensor.
        on_threshold_mm: Distance threshold for OFF → ON transition (pressed).
        off_threshold_mm: Distance threshold for ON → OFF transition (released, with hysteresis).
        last_present: Debounced ON/OFF state. True = pressed.
        raw_present: Instantaneous threshold-based state at last poll.
        on_count: Consecutive frames raw_present is True.
        off_count: Consecutive frames raw_present is False.
        last_change_time: Last time last_present was updated (monotonic seconds).
    """
    sensor: adafruit_vl53l0x.VL53L0X
    key: KeyId
    on_threshold_mm: int
    off_threshold_mm: int
    last_present: bool = False
    raw_present: bool = False
    on_count: int = 0
    off_count: int = 0
    last_change_time: float = 0.0


# ---------------------------------------------------------------------------
# IRInput
# ---------------------------------------------------------------------------

class IRInput:
    """
    Multi-sensor IR input system using VL53L0X time-of-flight sensors.

    Features:
        - Uses multiple sensors with XSHUT pins to assign unique I2C addresses.
        - Each sensor maps directly to one KeyId (e.g., piano keys).
        - Emits NOTE_ON when the debounced state transitions OFF → ON.
        - Emits NOTE_OFF when the debounced state transitions ON → OFF.

    Behavior:
        - raw_present = (distance < threshold) with hysteresis.
        - Several consecutive frames of raw_present True/False are required before changing the debounced last_present state.
        - OFF→ON transitions are protected by a cooldown to avoid ghost hits after the hand leaves the sensor.

    Note:
        Piano mode usually consumes these NOTE events. Rhythm mode ignores IR input.
    """

    def __init__(
        self,
        on_threshold_mm: int = 220,   # ~32cm: hand detected if closer than this
        off_threshold_mm: int = 260,  # ~38cm: hand considered gone if farther than this
        debug: bool = False,
        default_velocity: float = 1.0,
        cooldown_sec: float = 0.05,   # OFF→ON cooldown to prevent ghost hits after hand leaves
        on_stable_frames: int = 1,    # Number of consecutive frames for ON debounce
        off_stable_frames: int = 1,   # Number of consecutive frames for OFF debounce
    ) -> None:
        self.debug = debug
        self.on_threshold_mm = on_threshold_mm
        self.off_threshold_mm = off_threshold_mm
        self.default_velocity = max(0.0, min(1.0, default_velocity))
        self.cooldown_sec = cooldown_sec
        self.on_stable_frames = on_stable_frames
        self.off_stable_frames = off_stable_frames

        # -------------------------------------------------------------------
        # Create shared I2C bus
        # -------------------------------------------------------------------
        i2c = busio.I2C(board.SCL, board.SDA)

        # -------------------------------------------------------------------
        # XSHUT pins (one per sensor)
        # IMPORTANT: Must match your actual wiring!
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

        # Each sensor must receive a unique I2C address
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

        time.sleep(0.01)

        # -------------------------------------------------------------------
        # Step 2: Bring sensors up one at a time and assign new address
        # -------------------------------------------------------------------
        sensors: List[adafruit_vl53l0x.VL53L0X] = []

        for idx, (dio, new_addr) in enumerate(zip(xshut_ios, addresses)):
            # 1) Enable this sensor only
            dio.value = True
            time.sleep(0.05)

            # 2) Create sensor at default address (0x29)
            sensor = adafruit_vl53l0x.VL53L0X(i2c)

            # 3) Change to new unique address
            sensor.set_address(new_addr)

            if self.debug:
                print(f"[IR] Sensor {idx} assigned I2C address 0x{new_addr:02X}")

            sensors.append(sensor)

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

    # -----------------------------------------------------------------------
    # Poll sensors and produce NOTE_ON / NOTE_OFF events
    # -----------------------------------------------------------------------

    def poll(self) -> List[InputEvent]:
        """
        Read all VL53L0X sensors once and produce a list of InputEvent objects.

        - raw_present is calculated based on distance threshold and hysteresis.
        - last_present becomes True only after on_stable_frames consecutive raw_present=True.
        - last_present becomes False only after off_stable_frames consecutive raw_present=False.
        - OFF→ON transitions are ignored if they occur within cooldown_sec, to avoid ghost hits after hand leaves.
        """
        events: List[InputEvent] = []

        now = time.monotonic()

        for ch in self.channels:
            # Read sensor distance (in mm)
            try:
                distance = ch.sensor.range
            except OSError:
                if self.debug:
                    print(f"[IR] Read error on key={ch.key}")
                continue

            # Calculate raw_present with hysteresis
            if not ch.raw_present:
                raw_present = distance < ch.on_threshold_mm
            else:
                raw_present = distance < ch.off_threshold_mm

            ch.raw_present = raw_present

            # Update on_count / off_count for debouncing
            if raw_present:
                ch.on_count += 1
                ch.off_count = 0
            else:
                ch.off_count += 1
                ch.on_count = 0

            debounced_present = ch.last_present

            # Debounce OFF → ON
            if not ch.last_present:
                # Currently OFF, check if should become ON
                if ch.on_count >= self.on_stable_frames:
                    # Check cooldown: do not allow ON immediately after OFF
                    if (now - ch.last_change_time) >= self.cooldown_sec:
                        debounced_present = True
                        ch.last_change_time = now
                        if self.debug:
                            print(
                                f"[IR] key={int(ch.key)} DEBOUNCED ON "
                                f"(dist={distance}mm, on_count={ch.on_count})"
                            )
                    else:
                        # Still in cooldown, remain OFF
                        if self.debug:
                            print(
                                f"[IR] key={int(ch.key)} OFF→ON suppressed by cooldown "
                                f"(dt={now - ch.last_change_time:.3f}s)"
                            )
            # Debounce ON → OFF
            else:
                # Currently ON, check if should become OFF
                if ch.off_count >= self.off_stable_frames:
                    debounced_present = False
                    ch.last_change_time = now
                    if self.debug:
                        print(
                            f"[IR] key={int(ch.key)} DEBOUNCED OFF "
                            f"(dist={distance}mm, off_count={ch.off_count})"
                        )

            # Emit NOTE_ON / NOTE_OFF on debounced state change
            if debounced_present != ch.last_present:
                if debounced_present:
                    # OFF → ON → NOTE_ON
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
                            f"[IR] NOTE_ON key={ch.key} "
                            f"dist={distance}mm vel={velocity:.2f}"
                        )
                else:
                    # ON → OFF → NOTE_OFF
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
