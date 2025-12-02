# src/logic/modes/rhythm_mode.py

import math
from typing import List

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.config.keys import ALL_KEYS
from src.logic.input_event import InputEvent, EventType


class RhythmMode:
    """
    Rhythm mode logic.

    Currently:
      - Plays a simple wave animation across all keys.
      - Ignores input events (will be used later for scoring).
    """

    def __init__(self, led: LedMatrix) -> None:
        self.led = led
        self.start_time: float | None = None

    def reset(self, now: float) -> None:
        self.start_time = now

    def handle_events(self, events: List[InputEvent]) -> None:
        # Placeholder for future rhythm game scoring:
        # for ev in events:
        #     if ev.type == EventType.NOTE_ON and ev.key is not None:
        #         print(f"Rhythm hit on key {ev.key}")
        pass

    def update(self, now: float) -> None:
        if self.start_time is None:
            self.start_time = now

        t = now - self.start_time

        self.led.clear_all()

        for i, key in enumerate(ALL_KEYS):
            phase = t * 3.0 - i * 0.5
            wave = (math.sin(phase) + 1.0) / 2.0     # 0..1
            brightness = 0.1 + 0.9 * wave            # 0.1..1.0
            color = (0, 80, 255)
            self.led.fill_key(key, color, brightness)

        self.led.show()
