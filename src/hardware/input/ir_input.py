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


@dataclass
class IRSensorChannel:
    """
    One IR distance sensor mapped to one piano key.
    """
    sensor: adafruit_vl53l0x.VL53L0X
    key: KeyId
    on_threshold_mm: int
    off_threshold_mm: int
    last_present: bool = False


class IRInput:
    """
    Multi-sensor IR input (VL53L0X).

    - Uses XSHUT pins to bring up sensors one by one.
    - Each sensor gets a unique I2C address (0x30, 0x31, ...).
    - Each sensor controls one KeyId.
    - While "present" is True, we continuously emit NOTE_ON with
      brightness mapped from distance.
    """

    def __init__(
        self,
        on_threshold_mm: int = 240,
        off_threshold_mm: int = 260,
        debug: bool = False,
        default_velocity: float = 1.0,   # ★ 新增
    ) -> None:
        self.debug = debug
        self.on_threshold_mm = on_threshold_mm
        self.off_threshold_mm = off_threshold_mm
        self.default_velocity = max(0.0, min(1.0, default_velocity))


        # ---------- shared I2C bus ----------
        i2c = busio.I2C(board.SCL, board.SDA)

        # ---------- XSHUT pins for each sensor ----------
        # TODO: change these pins to match your wiring!
        xshut_pins = [
            board.D21,   # Sensor 0 → KeyId.KEY_0
            board.D20,   # Sensor 1 → KeyId.KEY_1
            board.D16,  # Sensor 2 → KeyId.KEY_2
            board.D26,  # Sensor 3 → KeyId.KEY_3
            board.D12,  # Sensor 4 → KeyId.KEY_4
        ]

        # Which key each sensor controls
        key_map = [
            KeyId.KEY_0,
            KeyId.KEY_1,
            KeyId.KEY_2,
            KeyId.KEY_3,
            KeyId.KEY_4,
        ]

        # I2C addresses to assign to sensors (must be unique)
        # addresses = [0x30, 0x31, 0x32, 0x33, 0x34]
        addresses = [0x30, 0x31, 0x32, 0x33, 0x34]
    
        if len(xshut_pins) != len(key_map) or len(key_map) != len(addresses):
            raise ValueError("xshut_pins, key_map, addresses length must match")

        # ---------- Bring all sensors into reset (shutdown) ----------
        xshut_ios: List[digitalio.DigitalInOut] = []
        for pin in xshut_pins:
            dio = digitalio.DigitalInOut(pin)
            dio.direction = digitalio.Direction.OUTPUT
            dio.value = False  # LOW = shutdown
            xshut_ios.append(dio)

        time.sleep(0.01)  # small delay to ensure all are off

        # ---------- Bring up each sensor one by one and assign new address ----------
        sensors: List[adafruit_vl53l0x.VL53L0X] = []

        for idx, (dio, addr) in enumerate(zip(xshut_ios, addresses)):
            # 1) Turn ON this sensor only
            dio.value = True
            time.sleep(0.05)  # wait for sensor boot

            # 2) Create VL53L0X at default address 0x29
            sensor = adafruit_vl53l0x.VL53L0X(i2c)

            # 3) Immediately change its I2C address
            sensor.set_address(addr)

            if self.debug:
                print(f"[IR] Sensor {idx} brought up at I2C address 0x{addr:02X}")

            sensors.append(sensor)

        # At this point:
        #  - Sensor 0 → addr 0x30
        #  - Sensor 1 → addr 0x31
        #  - ...
        # XSHUT pins stay HIGH to keep sensors on.

        # ---------- Build channel list (sensor ↔ key) ----------
        self.channels: List[IRSensorChannel] = []
        for sensor, key in zip(sensors, key_map):
            ch = IRSensorChannel(
                sensor=sensor,
                key=key,
                on_threshold_mm=self.on_threshold_mm,
                off_threshold_mm=self.off_threshold_mm,
            )
            self.channels.append(ch)


    # --------------------------------------------------------------
    # Poll all sensors, emit NOTE_ON / NOTE_OFF with continuous brightness
    # --------------------------------------------------------------
    def poll(self) -> List[InputEvent]:
        events: List[InputEvent] = []

        for ch in self.channels:
            try:
                distance = ch.sensor.range  # in mm
            except OSError:
                if self.debug:
                    print(f"[IR] I2C error while reading sensor for key={ch.key}")
                continue

            # Hysteresis for ON/OFF
            if not ch.last_present:
                # previously OFF → turn ON only when closer than on_threshold
                present = distance < ch.on_threshold_mm
            else:
                # previously ON → stay ON until farther than off_threshold
                present = distance < ch.off_threshold_mm

            if self.debug:
                print(
                    f"[IR] key={int(ch.key)} dist={distance}mm "
                    f"(on<{ch.on_threshold_mm}, off>{ch.off_threshold_mm}) "
                    f"last={ch.last_present} -> present={present}"
                )

            if present:
                # 手在可視為「按著」的區域內 → 每一幀都發 NOTE_ON
                velocity = getattr(self, "default_velocity", 1.0)
                ev = InputEvent(
                    type=EventType.NOTE_ON,
                    key=ch.key,
                    velocity=velocity,
                )
                events.append(ev)

                if self.debug:
                    print(
                        f"[IR] NOTE_ON (binary) key={ch.key}, "
                        f"dist={distance}mm, vel={velocity:.2f}"
                    )

            else:
                # 剛從 ON → OFF 才發 NOTE_OFF 一次
                if ch.last_present:
                    ev = InputEvent(
                        type=EventType.NOTE_OFF,
                        key=ch.key,
                    )
                    events.append(ev)
                    if self.debug:
                        print(f"[IR] NOTE_OFF key={ch.key}")

            ch.last_present = present

        return events
