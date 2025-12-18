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
    Represents one VL53L0X distance sensor mapped to one KeyId.

    Attributes:
        sensor:
            The VL53L0X sensor instance.

        key:
            Logical key assigned to this sensor.

        on_threshold_mm:
            Distance threshold for transitioning OFF → ON.
            If distance < on_threshold → key considered "pressed".

        off_threshold_mm:
            Distance threshold for transitioning ON → OFF.
            Provides hysteresis so the key does not rapidly toggle.

        last_present:
            Debounced ON/OFF state. True = active/pressed.

        raw_present:
            Instantaneous threshold-based state at the last poll.

        on_count / off_count:
            Number of consecutive frames that raw_present is True/False.
            用來做「穩定樣本」判斷，避免單一 frame 噪聲誤觸發。

        last_change_time:
            Time (monotonic seconds) when last_present was last updated.
            用來做 OFF→ON 的 cooldown，避免手剛離開時的 noise 誤觸發。
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
        • Uses multiple sensors with XSHUT pins to assign unique I2C addresses.
        • Each sensor maps directly to one KeyId (e.g., piano keys).
        • Emits NOTE_ON when the debounced state transitions OFF → ON.
        • Emits NOTE_OFF when the debounced state transitions ON → OFF.

    Behavior:
        - raw_present = (distance < threshold) with hysteresis.
        - We require several consecutive frames of raw_present True/False
          before changing the debounced last_present state.
        - OFF→ON transitions are further protected by a small cooldown,
          to avoid "late" ghost hits after the hand leaves the sensor.

    NOTE:
        Piano mode usually consumes these NOTE events.
        Rhythm mode ignores IR input.
    """

    def __init__(
        self,
        on_threshold_mm: int = 220,   # ~32cm 以內算「有手」
        off_threshold_mm: int = 260,  # ~38cm 以上才算「真的離開」
        debug: bool = False,
        default_velocity: float = 1.0,
        cooldown_sec: float = 0.05,   # OFF→ON 冷卻時間，防止手離開後短時間內 ghost hit
        on_stable_frames: int = 1,    # raw_present 連續幾 frame 才算 ON
        off_stable_frames: int = 1,   # raw_present 連續幾 frame 才算 OFF
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
        # IMPORTANT: must match your real wiring!
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
    # Poll sensors → produce NOTE_ON / NOTE_OFF events
    # -----------------------------------------------------------------------

    def poll(self) -> List[InputEvent]:
        """
        Read all VL53L0X sensors once and produce a list of InputEvent objects.

        - raw_present 依據距離門檻 + hysteresis 計算。
        - 連續 on_stable_frames 的 raw_present=True 才會把 last_present 變成 True。
        - 連續 off_stable_frames 的 raw_present=False 才會把 last_present 變成 False。
        - OFF→ON transition 若發生在 cooldown_sec 內則被忽略，避免手離開後的 ghost hit。
        """
        events: List[InputEvent] = []

        now = time.monotonic()

        for ch in self.channels:
            # -----------------------------
            # Read sensor
            # -----------------------------
            try:
                distance = ch.sensor.range  # in mm
            except OSError:
                if self.debug:
                    print(f"[IR] Read error on key={ch.key}")
                continue

            # -----------------------------
            # raw_present with hysteresis
            # -----------------------------
            if not ch.raw_present:
                raw_present = distance < ch.on_threshold_mm
            else:
                raw_present = distance < ch.off_threshold_mm

            ch.raw_present = raw_present

            # -----------------------------
            # Update on_count / off_count
            # -----------------------------
            if raw_present:
                ch.on_count += 1
                ch.off_count = 0
            else:
                ch.off_count += 1
                ch.on_count = 0

            debounced_present = ch.last_present

            # -----------------------------
            # Debounce OFF → ON
            # -----------------------------
            if not ch.last_present:
                # 目前視為 OFF，要不要變成 ON？
                if ch.on_count >= self.on_stable_frames:
                    # 再檢查 cooldown：剛 OFF 完的短時間內不要立刻再 ON
                    if (now - ch.last_change_time) >= self.cooldown_sec:
                        debounced_present = True
                        ch.last_change_time = now
                        if self.debug:
                            print(
                                f"[IR] key={int(ch.key)} DEBOUNCED ON "
                                f"(dist={distance}mm, on_count={ch.on_count})"
                            )
                    else:
                        # 在 cooldown 期間內，維持 OFF
                        if self.debug:
                            print(
                                f"[IR] key={int(ch.key)} OFF→ON suppressed by cooldown "
                                f"(dt={now - ch.last_change_time:.3f}s)"
                            )

            # -----------------------------
            # Debounce ON → OFF
            # -----------------------------
            else:
                # 目前視為 ON，要不要變成 OFF？
                if ch.off_count >= self.off_stable_frames:
                    debounced_present = False
                    ch.last_change_time = now
                    if self.debug:
                        print(
                            f"[IR] key={int(ch.key)} DEBOUNCED OFF "
                            f"(dist={distance}mm, off_count={ch.off_count})"
                        )

            # -----------------------------
            # Emit NOTE_ON / NOTE_OFF on debounced state change
            # -----------------------------
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
