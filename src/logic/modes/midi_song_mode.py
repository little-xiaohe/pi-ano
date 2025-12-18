# src/logic/modes/midi_song_mode.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

import random
import math
import mido

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.config.keys import (
    KeyId,
    KEY_COLOR_PALETTES,  # still used to pick a palette per song (for consistency)
    KEY_ZONES,           # used to know which x columns belong to which key
)
from src.hardware.audio.audio_engine import AudioEngine
from src.logic.input_event import InputEvent, EventType


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# MidiSongMode
# ---------------------------------------------------------------------------

class MidiSongMode:
    """
    Mode: play songs from a MIDI playlist & light 5 LED keys.

    - Playlist is a sorted list of MIDI files from `midi_folder`.
    - Playback order is sequential (0,1,2,...,N-1) and loops.
    - If loop_playlist=True: automatically go to next song when finished.
    - Press "next song" (KEY_3 via InputManager) to skip to the next in order.
    - LED:
        * Full-panel moving rainbow gradient.
        * Columns belonging to keys that are currently active get brighter.
    """

    def __init__(
        self,
        led: LedMatrix,
        audio: Optional[AudioEngine],
        midi_folder: str = "/home/pi/pi-ano/src/hardware/audio/assets/midi/song",
        loop_playlist: bool = True,
        debug: bool = False,
    ) -> None:
        self.led = led
        self.audio = audio
        self.debug = debug
        self.loop_playlist = loop_playlist

        self.start_time: Optional[float] = None

        # --- build playlist (sorted = deterministic order) ---
        folder = Path(midi_folder)
        self.playlist: List[Path] = sorted(
            [p for p in folder.glob("*.mid*") if p.is_file()]
        )
        if not self.playlist:
            raise FileNotFoundError(f"No MIDI files found in folder: {folder}")

        # index of current song within playlist (0..len-1)
        self._song_index: int = 0

        self.current_song: Optional[Path] = None
        self.events: List[MidiNoteEvent] = []
        self.next_on_index: int = 0
        self.next_off_index: int = 0
        self.active_led_notes: Dict[KeyId, ActiveLedNote] = {}

        # Precompute x → key mapping for the LED matrix
        self._x_to_key: Dict[int, Optional[KeyId]] = self._build_x_to_key()

        # Parameters for rainbow animation
        self.rainbow_time_speed: float = 0.06   # how fast hue cycles over time
        self.rainbow_spatial_span: float = 0.35 # hue difference from left to right

        # When receiving EventType.NEXT_SONG (from keyboard "next"), we set a flag
        # and handle the actual skip in update(now), which has the proper timestamp.
        self._skip_requested: bool = False

    # ------------------------------------------------------------------
    # x → key mapping
    # ------------------------------------------------------------------
    def _build_x_to_key(self) -> Dict[int, Optional[KeyId]]:
        """
        Build a mapping from x-column to KeyId (or None if that x is border).

        Uses KEY_ZONES from the central key config.
        Assumes KEY_ZONES[x0, x1] are inclusive ranges.
        """
        mapping: Dict[int, Optional[KeyId]] = {}
        width = self.led.width

        for x in range(width):
            mapping[x] = None

        for key, (x0, x1) in KEY_ZONES.items():
            start = max(0, x0)
            end = min(width - 1, x1)
            for x in range(start, end + 1):
                mapping[x] = key

        return mapping

    # ------------------------------------------------------------------
    # Small HSV → RGB helper (0.0~1.0 → 0~255)
    # ------------------------------------------------------------------
    @staticmethod
    def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
        """
        Convert HSV (0.0~1.0) to RGB (0~255).
        Simple implementation, good enough for LED gradients.
        """
        h = h % 1.0
        s = max(0.0, min(1.0, s))
        v = max(0.0, min(1.0, v))

        i = int(h * 6.0)
        f = (h * 6.0) - i
        p = v * (1.0 - s)
        q = v * (1.0 - f * s)
        t = v * (1.0 - (1.0 - f) * s)
        i = i % 6

        if i == 0:
            r, g, b = v, t, p
        elif i == 1:
            r, g, b = q, v, p
        elif i == 2:
            r, g, b = p, v, t
        elif i == 3:
            r, g, b = p, q, v
        elif i == 4:
            r, g, b = t, p, v
        else:
            r, g, b = v, p, q

        return (
            int(r * 255 + 0.5),
            int(g * 255 + 0.5),
            int(b * 255 + 0.5),
        )

    # ------------------------------------------------------------------
    # Playlist / song loading
    # ------------------------------------------------------------------
    def _load_song_events(self, midi_path: Path) -> List[MidiNoteEvent]:
        """
        Parse one MIDI file into a list of MidiNoteEvent.
        """
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

        # Fallback for notes without explicit note_off
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
    # Lifecycle / playlist control
    # ------------------------------------------------------------------
    def _start_song_by_index(self, index: int, now: float) -> None:
        """
        Start playing song at playlist[index], with wrapping.
        """
        n = len(self.playlist)
        if n == 0:
            return

        self._song_index = index % n
        song_path = self.playlist[self._song_index]

        # Random palette per song (can be changed to deterministic if needed)
        palette = random.choice(KEY_COLOR_PALETTES)
        self.led.set_key_palette(palette)

        self.current_song = song_path
        self.events = self._load_song_events(song_path)
        self.start_time = now
        self.next_on_index = 0
        self.next_off_index = 0
        self.active_led_notes.clear()

        # Ensure all notes are off when we start
        if self.audio is not None:
            self.audio.stop_all()

        if self.debug:
            print(
                f"[MidiSongMode] Start playing index={self._song_index} "
                f"song={song_path.name} at t={now:.3f}"
            )

    def _start_next_song(self, now: float) -> None:
        """
        Convenience: jump to next song in playlist order.
        """
        self._start_song_by_index(self._song_index + 1, now)

    def reset(self, now: float) -> None:
        """
        Called when entering song mode.

        Strategy:
        - Always start from the first song in the sorted playlist (index 0).
        """
        self._start_song_by_index(0, now)

    def handle_events(self, events: List[InputEvent]) -> None:
        """
        Handle external input in song mode.

        - EventType.NEXT_SONG (e.g., from keyboard "next")
            → request skip in the next update().
        """
        for ev in events:
            if ev.type == EventType.NEXT_SONG:
                self._skip_requested = True
                if self.debug:
                    print("[MidiSongMode] NEXT_SONG event received → skip requested")

    # ------------------------------------------------------------------
    # Main update (scheduler)
    # ------------------------------------------------------------------
    def update(self, now: float) -> None:
        """
        Main update loop for song mode. Handles note scheduling, LED updates, and song transitions.
        """
        # Handle pending skip request (from keyboard "next")
        if self._skip_requested:
            self._skip_requested = False
            self._start_next_song(now)
            return

        if self.start_time is None:
            # First update → start current index (usually 0 after reset)
            self._start_song_by_index(self._song_index, now)

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

        # 3) update LEDs (rainbow gradient + key highlights)
        self._update_leds(t)

        # 4) end of song?
        if self.next_off_index >= len(self.events) and not self.active_led_notes:
            if self.loop_playlist:
                # Go to next song in playlist order (with wrap-around)
                self._start_next_song(now)
            else:
                # Stay on the last frame of the song
                pass

    # ------------------------------------------------------------------
    # Helpers: audio + LED
    # ------------------------------------------------------------------
    def _trigger_note_on(self, ev: MidiNoteEvent, t: float) -> None:
        """
        Trigger one NOTE_ON (audio + add to active_led_notes).
        """
        key = self._midi_note_to_key(ev.midi_note)

        self.active_led_notes[key] = ActiveLedNote(
            key=key,
            velocity=ev.velocity,
            end_time=ev.end_time,
        )

        if self.audio is not None:
            try:
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
        """
        Trigger NOTE_OFF (audio only; LED is handled by _update_leds).
        """
        if self.audio is not None:
            try:
                self.audio.note_off_midi(ev.midi_note)
            except Exception as e:
                if self.debug:
                    print("[MidiSongMode] audio note_off_midi error:", e)

        if self.debug:
            print(f"[MidiSongMode] NOTE_OFF t={t:.3f}s midi={ev.midi_note}")

    def _update_leds(self, t: float) -> None:
        """
        Draw LEDs based on active_led_notes, with a full-panel rainbow gradient.

        - Rainbow hue slowly scrolls over time and across x.
        - Columns belonging to keys that are currently active are brighter.
        - Borders / non-key columns are dimmer background.
        """
        # Remove expired LED notes
        to_remove: List[KeyId] = []
        for key, active in self.active_led_notes.items():
            if t >= active.end_time:
                to_remove.append(key)
        for key in to_remove:
            self.active_led_notes.pop(key, None)

        width = self.led.width
        height = self.led.height

        self.led.clear_all()

        # strength: 0.0~1.0 based on velocity, clamped
        active_strength: Dict[KeyId, float] = {}
        for key, active in self.active_led_notes.items():
            strength = max(0.2, min(1.0, active.velocity))
            active_strength[key] = strength

        # Draw rainbow gradient column by column
        for x in range(width):
            key_for_col = self._x_to_key.get(x)

            h = (
                self.rainbow_time_speed * t
                + self.rainbow_spatial_span * (x / max(1, width - 1))
            ) % 1.0

            if key_for_col is not None and key_for_col in active_strength:
                s = 1.0
                v = 0.45 + 0.45 * active_strength[key_for_col]  # 0.45~0.9
            elif key_for_col is not None:
                s = 1.0
                v = 0.18
            else:
                s = 0.9
                v = 0.08

            r, g, b = self._hsv_to_rgb(h, s, v)

            for y in range(height):
                y_norm = (y / max(1, height - 1))
                bump = 1.0 + 0.15 * math.cos((y_norm - 0.5) * math.pi)
                rr = int(max(0, min(255, r * bump)))
                gg = int(max(0, min(255, g * bump)))
                bb = int(max(0, min(255, b * bump)))

                self.led.set_xy(x, y, (rr, gg, bb))

        self.led.show()

    def skip_to_next(self, now: float) -> None:
        """
        Skip current song and immediately start the next one in playlist order.
        """
        # Stop all current notes to avoid hanging sounds
        if self.audio is not None:
            try:
                self.audio.stop_all()
            except Exception as e:
                if self.debug:
                    print("[MidiSongMode] stop_all error in skip_to_next:", e)

        # Clear LEDs
        self.led.clear_all()
        self.led.show()

        # Start next song in sequence
        self._start_next_song(now)

        if self.debug:
            print("[MidiSongMode] Skipped to next song by external trigger")
