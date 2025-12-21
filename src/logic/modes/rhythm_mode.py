# src/logic/modes/rhythm_mode.py

from __future__ import annotations

import math
import time
from typing import List, Optional, Dict, Tuple

import mido

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.config.keys import KeyId
from src.logic.input_event import InputEvent, EventType
from src.hardware.audio.audio_engine import AudioEngine

from src.logic.modes.rhythm_chart import ChartNote
from src.logic.modes.rhythm_audio import AudioScheduler

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_MIDI_PATHS: Dict[str, str] = {
    "easy":   "/home/pi/pi-ano/src/hardware/audio/assets/midi/rhythm/twinkle-twinkle-little-star.mid",
    "medium": "/home/pi/pi-ano/src/hardware/audio/assets/midi/rhythm/The_Pink_Panther.mid",
    "hard":   "/home/pi/pi-ano/src/hardware/audio/assets/midi/rhythm/Cant_Help_Falling_In_Love.mid",
}

RHYTHM_KEYS: List[KeyId] = [
    KeyId.KEY_0,
    KeyId.KEY_1,
    KeyId.KEY_2,
    KeyId.KEY_3,
    KeyId.KEY_4,
]

LANE_COLORS: Dict[KeyId, Tuple[int, int, int]] = {
    KeyId.KEY_0: (255, 50, 50),
    KeyId.KEY_1: (255, 120, 0),
    KeyId.KEY_2: (0, 180, 255),
    KeyId.KEY_3: (150, 80, 255),
    KeyId.KEY_4: (255, 0, 170),
}

# Difficulty selection colors (Pi LED)
DIFFICULTY_SELECTION_COLORS: Dict[KeyId, Tuple[int, int, int]] = {
    KeyId.KEY_1: (255, 0, 0),     # HARD
    KeyId.KEY_2: (255, 255, 0),   # MEDIUM
    KeyId.KEY_3: (0, 200, 0),     # EASY
}

FEEDBACK_COLOR_PERFECT = (0, 255, 120)
FEEDBACK_COLOR_GOOD    = (255, 160, 0)
FEEDBACK_COLOR_MISS    = (255, 0, 0)

PERFECT_WINDOW_SEC = 0.08
GOOD_WINDOW_SEC    = 0.16
MISS_LATE_SEC      = 0.25

FALL_DURATION_SEC = 1.0
FEEDBACK_DURATION_SEC = 0.25

LEAD_IN_SEC = 1.0
TAIL_HOLD_SEC = 4.0


class RhythmMode:
    """
    Rhythm mode.

    IMPORTANT CHANGE:
      - When phase == "DONE", we DO NOT clear/show LEDs every frame anymore.
        We only clear LEDs once when entering DONE (in _check_done_and_finish),
        to avoid flicker when InputManager wants to render mode colors.
    """

    def __init__(
        self,
        led: LedMatrix,
        audio: Optional[AudioEngine] = None,
        midi_paths: Optional[Dict[str, str]] = None,
        debug: bool = True,
    ) -> None:
        self.led = led
        self.audio = audio
        self.debug = debug

        self._time_fn = time.monotonic

        self.midi_paths: Dict[str, str] = midi_paths or DEFAULT_MIDI_PATHS.copy()

        self.difficulty: str = "easy"
        self.midi_path: str = self.midi_paths[self.difficulty]

        self.phase: str = "WAIT_COUNTDOWN"  # "WAIT_COUNTDOWN" / "PLAY" / "DONE"
        self.play_start: float | None = None

        self.chart_notes: List[ChartNote] = []
        self._notes_built: bool = False
        self._miss_index: int = 0

        self.score: int = 0
        self.total_notes: int = 0
        self.max_score: int = 0

        self._key_x_ranges = self._build_key_x_ranges()

        self.feedback_until_song_time: float | None = None
        self.feedback_color: Optional[Tuple[int, int, int]] = None

        self.render_start_index: int = 0

        self.audio_scheduler: Optional[AudioScheduler] = None

    # ------------------------------------------------------------------
    # External hooks for InputManager
    # ------------------------------------------------------------------
    def show_mode_colors(self) -> None:
        """Public helper: draw difficulty selection colors on Pi LED."""
        self._render_wait_countdown()

    def stop_audio(self) -> None:
        if self.audio_scheduler is not None:
            self.audio_scheduler.stop()
            try:
                self.audio_scheduler.join(timeout=0.1)
            except RuntimeError:
                pass
            self.audio_scheduler = None

        if self.debug:
            print("[Rhythm] stop_audio(): scheduler stopped (no stop_all)")

    def on_exit(self) -> None:
        if self.debug:
            print("[Rhythm] on_exit() → stop_audio + phase=DONE")
        self.stop_audio()
        self.phase = "DONE"
        # Leaving rhythm mode: it's OK to hard clear once
        self.led.clear_all()
        self.led.show()

    def reset(self, now: float) -> None:
        self.stop_audio()

        self.phase = "WAIT_COUNTDOWN"
        self.play_start = None
        self.score = 0

        self._notes_built = False
        self._build_chart_from_midi()
        self._reset_notes_state()

        self.total_notes = len(self.chart_notes)
        self.max_score = self.total_notes * 2

        self.feedback_until_song_time = None
        self.feedback_color = None
        self.render_start_index = 0
        self._miss_index = 0

        if self.audio is not None and self.total_notes > 0:
            self.audio_scheduler = AudioScheduler(self.audio, self.chart_notes, self._time_fn)
        else:
            self.audio_scheduler = None

        self._render_wait_countdown()

        if self.debug:
            print(
                f"[Rhythm] reset: phase=WAIT_COUNTDOWN, "
                f"difficulty={self.difficulty}, midi={self.midi_path}, "
                f"notes={self.total_notes}, max_score={self.max_score}"
            )

    def start_play_after_countdown(self, now: float) -> None:
        if self.phase != "WAIT_COUNTDOWN":
            if self.debug:
                print(f"[Rhythm] start_play_after_countdown() ignored, phase={self.phase}")
            return

        self.phase = "PLAY"
        self.play_start = now + LEAD_IN_SEC
        self.render_start_index = 0
        self.feedback_color = None
        self.feedback_until_song_time = None
        self._miss_index = 0

        if self.audio_scheduler is not None:
            self.audio_scheduler.set_start_time(self.play_start)
            self.audio_scheduler.start()

        if self.debug:
            print(f"[Rhythm] PLAY will start at t={self.play_start:.3f} (lead_in={LEAD_IN_SEC}s)")

    def set_difficulty(self, difficulty: str) -> None:
        diff = difficulty.lower()
        if diff not in self.midi_paths:
            if self.debug:
                print(f"[Rhythm] set_difficulty: unknown '{difficulty}'")
            return

        self.difficulty = diff
        self.midi_path = self.midi_paths[diff]

        if self.debug:
            print(f"[Rhythm] set_difficulty -> {self.difficulty}, midi={self.midi_path}")

        self.stop_audio()
        self._notes_built = False
        self._build_chart_from_midi()
        self._reset_notes_state()

        self.total_notes = len(self.chart_notes)
        self.max_score = self.total_notes * 2
        self.render_start_index = 0
        self.feedback_color = None
        self.feedback_until_song_time = None
        self._miss_index = 0

        if self.audio is not None and self.total_notes > 0:
            self.audio_scheduler = AudioScheduler(self.audio, self.chart_notes, self._time_fn)
        else:
            self.audio_scheduler = None

        if self.phase == "WAIT_COUNTDOWN":
            self._render_wait_countdown()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _reset_notes_state(self) -> None:
        for n in self.chart_notes:
            n.hit = False
            n.judged = False
            n.score = 0

    def _build_key_x_ranges(self) -> Dict[KeyId, Tuple[int, int]]:
        w = self.led.width
        if w <= 2:
            return {k: (0, w) for k in RHYTHM_KEYS}

        inner_w = w - 2
        n = len(RHYTHM_KEYS)
        base = inner_w // n
        rem = inner_w % n

        ranges: Dict[KeyId, Tuple[int, int]] = {}
        x = 1
        for i, key in enumerate(RHYTHM_KEYS):
            span = base + (1 if i < rem else 0)
            x0 = x
            x1 = x + span
            ranges[key] = (x0, x1)
            x = x1
        return ranges

    def _key_x_range(self, key: KeyId) -> Tuple[int, int]:
        return self._key_x_ranges.get(key, (1, max(1, self.led.width - 1)))

    def _build_chart_from_midi(self) -> None:
        try:
            mid = mido.MidiFile(self.midi_path)
        except Exception as e:
            print(f"[Rhythm] Failed to load MIDI: {self.midi_path} ({e})")
            self.chart_notes = []
            return

        ticks_per_beat = mid.ticks_per_beat
        tempo = 500000
        time_sec = 0.0

        raw_notes: List[ChartNote] = []
        merged = mido.merge_tracks(mid.tracks)

        for msg in merged:
            if msg.time:
                dt = mido.tick2second(msg.time, ticks_per_beat, tempo)
                time_sec += dt

            if msg.is_meta and msg.type == "set_tempo":
                tempo = msg.tempo
                continue

            if msg.type == "note_on" and msg.velocity > 0:
                channel = getattr(msg, "channel", 0)
                if channel == 9:
                    continue

                midi_note = msg.note
                velocity = msg.velocity / 127.0
                key = self._midi_note_to_key(midi_note)

                raw_notes.append(
                    ChartNote(time=time_sec, midi_note=midi_note, key=key, velocity=velocity)
                )

        raw_notes.sort(key=lambda n: n.time)

        melody: List[ChartNote] = []
        if raw_notes:
            cluster: List[ChartNote] = [raw_notes[0]]
            cluster_eps = 0.08

            for note in raw_notes[1:]:
                if abs(note.time - cluster[-1].time) <= cluster_eps:
                    cluster.append(note)
                else:
                    best = max(cluster, key=lambda n: n.midi_note)
                    melody.append(best)
                    cluster = [note]

            best = max(cluster, key=lambda n: n.midi_note)
            melody.append(best)

        self.chart_notes = melody

        if self.debug:
            print(
                f"[Rhythm] MIDI parsed ({self.difficulty}): "
                f"raw={len(raw_notes)} → melody={len(melody)}"
            )

    def _midi_note_to_key(self, midi_note: int) -> KeyId:
        idx = (midi_note - 60) % 5
        idx = max(0, min(4, idx))
        return KeyId(idx)

    def _start_feedback(self, song_time: float, color: Tuple[int, int, int]) -> None:
        self.feedback_color = color
        self.feedback_until_song_time = song_time + FEEDBACK_DURATION_SEC

    def _register_hit(self, note: ChartNote, dt: float, song_time: float) -> None:
        if note.judged:
            return

        note.judged = True
        note.hit = True

        adt = abs(dt)
        if adt <= PERFECT_WINDOW_SEC:
            note.score = 2
        elif adt <= GOOD_WINDOW_SEC:
            note.score = 1
        else:
            note.score = 0

        if note.score > 0:
            self.score += note.score

        if note.score == 2:
            self._start_feedback(song_time, FEEDBACK_COLOR_PERFECT)
        elif note.score == 1:
            self._start_feedback(song_time, FEEDBACK_COLOR_GOOD)

        if self.debug:
            print(
                f"[Rhythm] HIT key={note.key} dt={dt:+.3f}s "
                f"score={note.score} total={self.score}"
            )

    def _register_miss(self, note: ChartNote, song_time: float) -> None:
        if note.judged:
            return
        note.judged = True
        note.score = 0
        self._start_feedback(song_time, FEEDBACK_COLOR_MISS)

        if self.debug:
            print(f"[Rhythm] MISS key={note.key}")

    def _update_miss_judgements(self, song_time: float) -> None:
        while self._miss_index < len(self.chart_notes):
            note = self.chart_notes[self._miss_index]
            if song_time < note.time + MISS_LATE_SEC:
                break

            if not note.judged:
                self._register_miss(note, song_time)

            self._miss_index += 1

    def handle_events(self, events: List[InputEvent]) -> None:
        if self.phase != "PLAY":
            return
        if self.play_start is None:
            return

        now = self._time_fn()
        song_time = now - self.play_start

        for ev in events:
            if ev.type != EventType.NOTE_ON:
                continue
            if ev.key is None:
                continue
            if ev.key not in RHYTHM_KEYS:
                continue

            lane_key = ev.key

            best_note: Optional[ChartNote] = None
            best_adt: float | None = None
            best_dt: float = 0.0

            for note in self.chart_notes:
                if note.key != lane_key:
                    continue
                if note.judged:
                    continue

                dt = song_time - note.time
                adt = abs(dt)

                if adt > MISS_LATE_SEC:
                    continue

                if best_adt is None or adt < best_adt:
                    best_adt = adt
                    best_dt = dt
                    best_note = note

            if best_note is not None:
                self._register_hit(best_note, best_dt, song_time)

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------
    def update(self, now: float) -> None:
        if self.phase == "WAIT_COUNTDOWN":
            self._render_wait_countdown()
            return

        if self.phase == "DONE":
            # ✅ DO NOTHING in DONE (avoid fighting with InputManager)
            return

        if self.play_start is None:
            self.play_start = now

        song_time = now - self.play_start

        self._update_miss_judgements(song_time)
        self._update_render_start_index(song_time)
        self._render_play(song_time)
        self._check_done_and_finish(song_time)

    # ------------------------------------------------------------------
    # WAIT_COUNTDOWN rendering
    # ------------------------------------------------------------------
    def _render_wait_countdown(self) -> None:
        self.led.clear_all()
        h = self.led.height

        for key, color in DIFFICULTY_SELECTION_COLORS.items():
            x0, x1 = self._key_x_range(key)
            for x in range(x0, x1):
                for y in range(h):
                    self.led.set_xy(x, y, color)

        self.led.show()

    # ------------------------------------------------------------------
    # Helpers for PLAY phase
    # ------------------------------------------------------------------
    def _update_render_start_index(self, song_time: float) -> None:
        cutoff_time = song_time - (FALL_DURATION_SEC + MISS_LATE_SEC)
        while (
            self.render_start_index < len(self.chart_notes)
            and self.chart_notes[self.render_start_index].time < cutoff_time
        ):
            self.render_start_index += 1

    def _check_done_and_finish(self, song_time: float) -> None:
        if not self.chart_notes:
            return

        if not all(n.judged for n in self.chart_notes):
            return

        last_time = self.chart_notes[-1].time
        if song_time < last_time + TAIL_HOLD_SEC:
            return

        # ✅ Enter DONE: clear LEDs ONCE
        self.phase = "DONE"
        self.led.clear_all()
        self.led.show()

        if self.debug:
            print(
                f"[Rhythm] DONE. score={self.score}/{self.max_score} "
                f"(notes={self.total_notes}, difficulty={self.difficulty})"
            )

    # ------------------------------------------------------------------
    # Rendering: falling blocks + feedback columns
    # ------------------------------------------------------------------
    def _compute_fall_progress(self, note: ChartNote, song_time: float) -> Optional[float]:
        dt_to_note = note.time - song_time

        if dt_to_note > FALL_DURATION_SEC:
            return None
        if dt_to_note < -MISS_LATE_SEC:
            return None

        if dt_to_note >= 0:
            t_from_start = FALL_DURATION_SEC - dt_to_note
            progress = t_from_start / FALL_DURATION_SEC
        else:
            progress = 1.0

        return max(0.0, min(1.0, progress))

    def _compute_note_color(self, note: ChartNote, progress: float, song_time: float) -> Tuple[int, int, int]:
        if note.hit:
            base_color = (255, 255, 255)
            boost = 1.0
        else:
            base_color = LANE_COLORS.get(note.key, (0, 180, 255))
            boost = 1.1 if abs(song_time - note.time) <= GOOD_WINDOW_SEC else 0.9

        brightness_factor = 0.4 + 0.6 * math.sqrt(progress)
        brightness_factor *= boost
        brightness_factor = max(0.4, min(1.2, brightness_factor))

        r = int(min(255, base_color[0] * brightness_factor))
        g = int(min(255, base_color[1] * brightness_factor))
        b = int(min(255, base_color[2] * brightness_factor))
        return (r, g, b)

    def _render_play(self, song_time: float) -> None:
        self.led.clear_all()

        w = self.led.width
        h = self.led.height

        for note in self.chart_notes[self.render_start_index:]:
            progress = self._compute_fall_progress(note, song_time)
            if progress is None:
                if note.time - song_time > FALL_DURATION_SEC:
                    break
                continue

            y_center = int((1.0 - progress) * (h - 1) + 0.5)

            color = self._compute_note_color(note, progress, song_time)
            x0, x1 = self._key_x_range(note.key)

            for x in range(x0, x1):
                for y in range(y_center - 1, y_center + 2):
                    if 0 <= y < h:
                        self.led.set_xy(x, y, color)

        if (
            self.feedback_color is not None
            and self.feedback_until_song_time is not None
            and self.play_start is not None
        ):
            if song_time <= self.feedback_until_song_time:
                left_x = 0
                right_x = w - 1
                for y in range(h):
                    self.led.set_xy(left_x, y, self.feedback_color)
                    self.led.set_xy(right_x, y, self.feedback_color)

        self.led.show()
