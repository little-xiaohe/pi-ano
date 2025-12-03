# src/logic/modes/midi_song_mode.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional
import random

import mido

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.config.keys import KeyId, KEY_COLOR_PALETTES
from src.hardware.audio.audio_engine import AudioEngine


@dataclass
class MidiNoteEvent:
    """One note from the MIDI file on a global timeline."""
    start_time: float      # seconds from song start
    end_time: float        # seconds from song start
    midi_note: int         # 0~127
    velocity: float        # 0.0 ~ 1.0


@dataclass
class ActiveLedNote:
    """A note currently lighting a LED key zone."""
    key: KeyId
    velocity: float
    end_time: float


class MidiSongMode:
    """
    Mode: play songs from a MIDI playlist & light 5 LED keys.

    - Own scheduler (next_on_index / next_off_index).
    - Playlist support: randomly pick a song from midi_folder.
    - If loop_playlist=True: automatically go to next song when finished.
    """

    def __init__(
        self,
        led: LedMatrix,
        audio: Optional[AudioEngine],
        midi_folder: str = "/home/pi/pi-ano/src/hardware/audio/assets/midi",
        loop_playlist: bool = True,
        debug: bool = False,
    ) -> None:
        self.led = led
        self.audio = audio
        self.debug = debug
        self.loop_playlist = loop_playlist

        self.start_time: Optional[float] = None

        # --- build playlist ---
        folder = Path(midi_folder)
        self.playlist: List[Path] = sorted(
            [p for p in folder.glob("*.mid*") if p.is_file()]
        )
        if not self.playlist:
            raise FileNotFoundError(f"No MIDI files found in folder: {folder}")

        self.current_song: Optional[Path] = None
        self.events: List[MidiNoteEvent] = []
        self.next_on_index: int = 0
        self.next_off_index: int = 0
        self.active_led_notes: Dict[KeyId, ActiveLedNote] = {}

    # ------------------------------------------------------------------
    # Playlist / song loading
    # ------------------------------------------------------------------
    def _pick_random_song(self) -> Path:
        song = random.choice(self.playlist)
        if self.debug:
            print(f"[MidiSongMode] Picked song: {song.name}")
        return song

    def _load_song_events(self, midi_path: Path) -> List[MidiNoteEvent]:
        """Parse one MIDI file into a list of MidiNoteEvent."""
        mid = mido.MidiFile(midi_path)

        events: List[MidiNoteEvent] = []
        active: Dict[int, tuple[float, float]] = {}  # midi_note -> (start_time, velocity)

        current_time = 0.0

        for msg in mid:
            current_time += msg.time  # already in seconds

            if msg.type == "note_on" and msg.velocity > 0:
                vel = msg.velocity / 127.0
                active[msg.note] = (current_time, vel)

            elif msg.type in ("note_off",) or (msg.type == "note_on" and msg.velocity == 0):
                if msg.note in active:
                    start_time, vel = active.pop(msg.note)
                    end_time = current_time
                    if end_time > start_time:
                        events.append(
                            MidiNoteEvent(
                                start_time=start_time,
                                end_time=end_time,
                                midi_note=msg.note,
                                velocity=vel,
                            )
                        )

        # fallback for notes without explicit note_off
        for note, (start_time, vel) in active.items():
            events.append(
                MidiNoteEvent(
                    start_time=start_time,
                    end_time=start_time + 0.5,
                    midi_note=note,
                    velocity=vel,
                )
            )

        events.sort(key=lambda e: e.start_time)

        if self.debug:
            print(f"[MidiSongMode] Loaded {len(events)} events from {midi_path.name}")

        return events

    # MIDI note → 5 LED keys (mod 5)
    def _midi_note_to_key(self, midi_note: int) -> KeyId:
        """
        Map MIDI note to 5 keys using modulo-5.

        - base C4 = 60
        - (midi_note - base) % 5 -> 0..4 → KEY_0..KEY_4
        """
        base = 60
        idx = (midi_note - base) % 5

        if idx == 0:
            return KeyId.KEY_0
        elif idx == 1:
            return KeyId.KEY_1
        elif idx == 2:
            return KeyId.KEY_2
        elif idx == 3:
            return KeyId.KEY_3
        else:
            return KeyId.KEY_4

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _start_new_song(self, now: float) -> None:
        """Pick a new song, load events, reset scheduler, change LED palette."""
        # 1) random palette for this song
        palette = random.choice(KEY_COLOR_PALETTES)
        self.led.set_key_palette(palette)

        # 2) pick song & load events
        self.current_song = self._pick_random_song()
        self.events = self._load_song_events(self.current_song)

        self.start_time = now
        self.next_on_index = 0
        self.next_off_index = 0
        self.active_led_notes.clear()

        # also ensure all notes are off when we start
        if self.audio is not None:
            self.audio.stop_all()

        if self.debug:
            print(f"[MidiSongMode] Start playing: {self.current_song.name} at t={now:.3f}")
            print(f"[MidiSongMode] Palette changed for this song")

    def reset(self, now: float) -> None:
        """
        Called when entering song mode.

        Strategy:
        - Every reset picks a new random song and restarts from beginning.
        """
        self._start_new_song(now)

    def handle_events(self, events: List[object]) -> None:
        """
        Currently ignore external input in song mode.

        If you later want "skip", "back", etc. via keyboard,
        you can interpret InputEvent here.
        """
        return

    # ------------------------------------------------------------------
    # Main update (scheduler)
    # ------------------------------------------------------------------
    def update(self, now: float) -> None:
        if self.start_time is None:
            # first update → pick a random song
            self._start_new_song(now)

        t = now - self.start_time
        eps = 0.002  # small tolerance

        # 1) trigger NOTE_ON
        while self.next_on_index < len(self.events):
            ev = self.events[self.next_on_index]
            if ev.start_time <= t + eps:
                self._trigger_note_on(ev, t)
                self.next_on_index += 1
            else:
                break

        # 2) trigger NOTE_OFF
        while self.next_off_index < len(self.events):
            ev = self.events[self.next_off_index]
            if ev.end_time <= t + eps:
                self._trigger_note_off(ev, t)
                self.next_off_index += 1
            else:
                break

        # 3) update LEDs
        self._update_leds(t)

        # 4) end of song?
        if self.next_off_index >= len(self.events) and not self.active_led_notes:
            if self.loop_playlist:
                # automatically move to next song
                self._start_new_song(now)
            else:
                # do nothing: stay at the end frame
                pass

    # ------------------------------------------------------------------
    # Helpers: audio + LED
    # ------------------------------------------------------------------
    def _trigger_note_on(self, ev: MidiNoteEvent, t: float) -> None:
        """Trigger one NOTE_ON (audio + add to active_led_notes)."""
        key = self._midi_note_to_key(ev.midi_note)

        # LED state
        self.active_led_notes[key] = ActiveLedNote(
            key=key,
            velocity=ev.velocity,
            end_time=ev.end_time,
        )

        # Audio
        if self.audio is not None:
            try:
                # velocity already in 0.0~1.0 range
                self.audio.note_on_midi(ev.midi_note, ev.velocity)
            except Exception as e:
                if self.debug:
                    print("[MidiSongMode] audio note_on_midi error:", e)

        if self.debug:
            song = self.current_song.name if self.current_song else "?"
            print(
                f"[MidiSongMode] NOTE_ON t={t:.3f}s song={song} "
                f"midi={ev.midi_note} -> key={int(key)}, vel={ev.velocity:.2f}"
            )

    def _trigger_note_off(self, ev: MidiNoteEvent, t: float) -> None:
        """Trigger NOTE_OFF (audio only; LED is handled by _update_leds)."""
        if self.audio is not None:
            try:
                self.audio.note_off_midi(ev.midi_note)
            except Exception as e:
                if self.debug:
                    print("[MidiSongMode] audio note_off_midi error:", e)

        if self.debug:
            print(f"[MidiSongMode] NOTE_OFF t={t:.3f}s midi={ev.midi_note}")

    def _update_leds(self, t: float) -> None:
        """Draw LEDs based on active_led_notes; remove expired notes."""
        self.led.clear_all()

        to_remove: List[KeyId] = []

        for key, active in self.active_led_notes.items():
            if t >= active.end_time:
                to_remove.append(key)
            else:
                brightness = max(0.1, min(1.0, active.velocity))
                self.led.fill_key(key, brightness=brightness)

        for key in to_remove:
            self.active_led_notes.pop(key, None)

        self.led.show()

    def skip_to_next(self, now: float) -> None:
        """
        Skip current song and immediately start a new random one.
        """
        # stop all current notes to avoid hanging sounds
        if self.audio is not None:
            try:
                self.audio.stop_all()
            except Exception as e:
                if self.debug:
                    print("[MidiSongMode] stop_all error in skip_to_next:", e)

        # clear LEDs
        self.led.clear_all()
        self.led.show()

        # start next song
        self._start_new_song(now)

        if self.debug:
            print("[MidiSongMode] Skipped to next song")
