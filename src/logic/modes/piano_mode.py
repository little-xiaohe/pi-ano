# src/logic/modes/piano_mode.py
import random
from dataclasses import dataclass
from typing import Dict, List

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.config.keys import KeyId, ALL_KEYS, make_rainbow_palette
from src.logic.input_event import InputEvent, EventType
from src.hardware.audio.audio_engine import AudioEngine


WHITE = (255, 255, 255)


@dataclass
class NoteState:
    """
    Internal per-key state for Piano mode.
    """
    key: KeyId
    is_on: bool
    velocity: float  # 0.0 ~ 1.0


class PianoMode:
    """
    Piano mode logic layer.

    - Keeps track of which keys are currently on/off.
    - Each key has a velocity (mapped to LED brightness).
    - Consumes NOTE_ON / NOTE_OFF events (from keyboard / IR / buttons).
    """

    def __init__(self, led: LedMatrix, audio: AudioEngine | None = None):
        self.led = led
        self.audio = audio
        self.notes: Dict[KeyId, NoteState] = {
            k: NoteState(key=k, is_on=False, velocity=1.0) for k in ALL_KEYS
        }

    # ---- high-level API for notes ----

    def note_on(self, key: KeyId, velocity: float = 1.0) -> None:
        if key not in self.notes:
            return

        v = max(0.0, min(1.0, velocity))
        state = self.notes[key]

        # 如果這個 key 已經是 ON：
        # → 只更新 velocity（讓 LED 亮度可以跟著變）
        # → 但是「不要再呼叫 audio.note_on」，避免聲音一直被 retrigger
        if state.is_on:
            state.velocity = v
            return

        # 第一次從 OFF → ON
        state.is_on = True
        state.velocity = v

        # ★ 這時候才觸發一次鋼琴音
        if self.audio is not None:
            self.audio.note_on(key, v)


    def note_off(self, key: KeyId) -> None:
        if key not in self.notes:
            return
        self.notes[key].is_on = False
        if self.audio is not None:
            self.audio.note_off(key)
        # print(f"[Piano] NOTE_OFF key={key}")

    def handle_events(self, events: List[InputEvent]) -> None:
        """
        Consume NOTE_ON / NOTE_OFF events from the input layer.

        We now use the shared EventType enum from logic.input_event.
        """
        for ev in events:
            if ev.type == EventType.NOTE_ON:
                self.note_on(ev.key, ev.velocity)
            elif ev.type == EventType.NOTE_OFF:
                self.note_off(ev.key)

    # ---- rendering ----

    def update(self, now: float) -> None:
        # 這一幀要畫什麼
        self.led.clear_all()

        any_on = False
        for key, state in self.notes.items():
            if state.is_on:
                any_on = True
                self.led.fill_key(key, brightness=state.velocity)

        # if any_on:
        #     print("[Piano] update: some keys ON")

        self.led.show()

    def randomize_palette(self) -> None:
        hue_offset = random.random()        # 0.0 ~ 1.0 隨機起始色
        palette = make_rainbow_palette(hue_offset=hue_offset)
        self.led.set_key_palette(palette)
