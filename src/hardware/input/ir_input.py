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
            Previous ON/OFF state. True = active/pressed.
    """
    sensor: adafruit_vl53l0x.VL53L0X
    key: KeyId
    on_threshold_mm: int
    off_threshold_mm: int
    last_present: bool = False


# ---------------------------------------------------------------------------
# IRInput
# ---------------------------------------------------------------------------

class IRInput:
    """
    Multi-sensor IR input system using VL53L0X time-of-flight sensors.

    Features:
        • Uses multiple sensors with XSHUT pins to assign unique I2C addresses.
        • Each sensor maps directly to one KeyId (e.g., piano keys).
        • Produces NOTE_ON continuously while a hand is detected close enough.
        • Produces NOTE_OFF when the hand leaves (based on hysteresis).

    Behavior:
        - "present" means the distance is within ON/OFF threshold rules.
        - While present, NOTE_ON is emitted every poll (good for velocity control).
        - When present transitions True → False, a single NOTE_OFF is emitted.

    NOTE:
        Piano mode usually consumes these NOTE events.
        Rhythm mode ignores IR input.
    """

    def __init__(
        self,
        on_threshold_mm: int = 220,
        off_threshold_mm: int = 260,
        debug: bool = False,
        default_velocity: float = 1.0,
    ) -> None:
        self.debug = debug
        self.on_threshold_mm = on_threshold_mm
        self.off_threshold_mm = off_threshold_mm
        self.default_velocity = max(0.0, min(1.0, default_velocity))

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

        for sensor, key in zip(sensors, key_map):
            self.channels.append(
                IRSensorChannel(
                    sensor=sensor,
                    key=key,
                    on_threshold_mm=self.on_threshold_mm,
                    off_threshold_mm=self.off_threshold_mm,
                )
            )

    # -----------------------------------------------------------------------
    # Poll sensors → produce NOTE_ON / NOTE_OFF events
    # -----------------------------------------------------------------------

    def poll(self) -> List[InputEvent]:
        """
        Read all VL53L0X sensors once and produce a list of InputEvent objects.

        NOTE_ON:
            Emitted *every frame* while hand is detected (present=True).
            Includes velocity (constant by default).

        NOTE_OFF:
            Emitted only once when present transitions True → False.
        """
        events: List[InputEvent] = []

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
            # Presence detection (hysteresis)
            # -----------------------------
            if not ch.last_present:
                present = distance < ch.on_threshold_mm
            else:
                present = distance < ch.off_threshold_mm

            if self.debug:
                print(
                    f"[IR] key={int(ch.key)} "
                    f"dist={distance}mm "
                    f"ON<th{ch.on_threshold_mm}, OFF>th{ch.off_threshold_mm} "
                    f"{ch.last_present} → {present}"
                )

            # -----------------------------
            # If present → continuous NOTE_ON
            # -----------------------------
            if present:
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

            # -----------------------------
            # If transitioned ON → OFF → NOTE_OFF
            # -----------------------------
            else:
                if ch.last_present:
                    events.append(
                        InputEvent(
                            type=EventType.NOTE_OFF,
                            key=ch.key,
                            source="ir",
                        )
                    )
                    if self.debug:
                        print(f"[IR] NOTE_OFF key={ch.key}")

            ch.last_present = present

        return events
