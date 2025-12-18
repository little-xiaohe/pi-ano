# src/logic/modes/piano_mode.py
import random
from dataclasses import dataclass
from typing import Dict, List

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.config.keys import KeyId, ALL_KEYS, make_rainbow_palette
from src.logic.input_event import InputEvent, EventType
from src.hardware.audio.audio_engine import AudioEngine


WHITE = (255, 255, 255)

# Enable this to print every NOTE_ON / NOTE_OFF event (with source)
DEBUG_PIANO_EVENTS = False


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
        """
        Turn on a key (NOTE_ON), update velocity, and trigger audio if newly pressed.
        """
        if key not in self.notes:
            return

        v = max(0.0, min(1.0, velocity))
        state = self.notes[key]

        # If this key is already ON:
        # → Only update velocity (so LED brightness can change)
        # → But do NOT call audio.note_on again to avoid retriggering sound
        if state.is_on:
            state.velocity = v
            return

        # First time OFF → ON
        state.is_on = True
        state.velocity = v

        # Trigger piano sound only once when key is pressed
        if self.audio is not None:
            self.audio.note_on(key, v)

    def note_off(self, key: KeyId) -> None:
        """
        Turn off a key (NOTE_OFF) and stop audio for that key.
        """
        if key not in self.notes:
            return
        self.notes[key].is_on = False
        if self.audio is not None:
            self.audio.note_off(key)

    def handle_events(self, events: List[InputEvent]) -> None:
        """
        Consume NOTE_ON / NOTE_OFF events from the input layer.
        """
        for ev in events:
            if DEBUG_PIANO_EVENTS and ev.type in (EventType.NOTE_ON, EventType.NOTE_OFF):
                print(
                    f"[Piano] EVENT {ev.type.name} "
                    f"key={ev.key} vel={ev.velocity} src={ev.source}"
                )

            if ev.type == EventType.NOTE_ON:
                self.note_on(ev.key, ev.velocity)
            elif ev.type == EventType.NOTE_OFF:
                self.note_off(ev.key)

    # ---- rendering ----

    def update(self, now: float) -> None:
        """
        Render the current frame: light up all keys that are ON with their velocity.
        """
        self.led.clear_all()

        for key, state in self.notes.items():
            if state.is_on:
                self.led.fill_key(key, brightness=state.velocity)

        self.led.show()

    def randomize_palette(self) -> None:
        """
        Randomize the key color palette using a random hue offset.
        """
        hue_offset = random.random()        # 0.0 ~ 1.0 random starting hue
        palette = make_rainbow_palette(hue_offset=hue_offset)
        self.led.set_key_palette(palette)
