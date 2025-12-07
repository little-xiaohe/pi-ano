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

# You can change this to any MIDI file you like.
DEFAULT_MIDI_PATH = (
    "/home/pi/pi-ano/src/hardware/audio/assets/midi/rhythm/twinkle-twinkle-little-star.mid"
)

# Rhythm mode uses the first 5 keys (0..4)
RHYTHM_KEYS: List[KeyId] = [
    KeyId.KEY_0,
    KeyId.KEY_1,
    KeyId.KEY_2,
    KeyId.KEY_3,
    KeyId.KEY_4,
]

# Base colors for each lane (before hit)
# Very high-saturation, clearly separated rainbow-like colors.
LANE_COLORS: Dict[KeyId, Tuple[int, int, int]] = {
    KeyId.KEY_0: (255, 40, 80),    # vivid red-pink
    KeyId.KEY_1: (255, 220, 40),   # bright yellow
    KeyId.KEY_2: (60, 255, 140),   # neon green / mint
    KeyId.KEY_3: (60, 210, 255),   # bright cyan
    KeyId.KEY_4: (200, 120, 255),  # strong violet
}

# Judge feedback colors (left/right columns)
# MISS => bright red
# PERFECT (2 pts) => matcha green
# GOOD (1 pt) => orange
FEEDBACK_COLOR_PERFECT = (170, 255, 120)  # 抹茶綠 (2 points, slightly brighter)
FEEDBACK_COLOR_GOOD    = (255, 190, 80)   # 橘色   (1 point, high saturation)
FEEDBACK_COLOR_MISS    = (255, 20, 20)    # 鮮紅色 (miss)

# Intro timing
INTRO_TOTAL_SEC = 4.0
INTRO_COUNTDOWN_START_SEC = 1.5
# Judge windows (seconds)
PERFECT_WINDOW_SEC = 0.08    # |dt| <= 80ms → 2 points
GOOD_WINDOW_SEC    = 0.16    # |dt| <= 160ms → 1 point
MISS_LATE_SEC      = 0.25    # later than this → miss

# Falling time: note appears at top at (time - FALL_DURATION_SEC),
# and reaches bottom exactly at ChartNote.time.
FALL_DURATION_SEC = 1.0

# Feedback lamp duration
FEEDBACK_DURATION_SEC = 0.25

# ---------------------------------------------------------------------------
# Simple 3x5 font for intro / countdown / result (flipped Y)
# ---------------------------------------------------------------------------

FONT_3x5: Dict[str, List[str]] = {
    "R": ["111", "101", "111", "110", "101"],
    "H": ["101", "101", "111", "101", "101"],
    "Y": ["101", "101", "111", "010", "010"],
    "T": ["111", "010", "010", "010", "010"],
    "M": ["101", "111", "111", "101", "101"],
    "G": ["011", "100", "101", "101", "011"],
    "A": ["010", "101", "111", "101", "101"],
    "E": ["111", "100", "110", "100", "111"],
    " ": ["000", "000", "000", "000", "000"],
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
    "/": ["001", "001", "010", "100", "100"],
}


# ---------------------------------------------------------------------------
# RhythmMode
# ---------------------------------------------------------------------------

class RhythmMode:
    """
    Rhythm game mode.

    - Uses a single MIDI file as the melody source.
    - Parses all notes, clusters by time, and keeps only the highest note
      in each cluster as the main melody.
    - Visuals:
        * Each note appears as a 3-cell tall falling block in the middle
          5 lanes (center columns of the LED matrix).
        * Leftmost and rightmost columns are reserved for hit feedback
          (red / green / orange).
    - Sound:
        * Melody playback is handled by AudioScheduler in a background
          thread, so timing is not affected by LED FPS.
    - Flow:
        1) INTRO: show "RHYTHM / GAME", then 5,4,3,2,1 countdown
        2) PLAY: falling notes; bottom is the hit timing
        3) DONE: show "score/max_score"
    """

    # ------------------------------------------------------------------
    # Construction / mode lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        led: LedMatrix,
        audio: Optional[AudioEngine] = None,
        midi_path: str = DEFAULT_MIDI_PATH,
        debug: bool = True,
    ) -> None:
        self.led = led
        self.audio = audio
        self.midi_path = midi_path
        self.debug = debug

        # Time function (shared with main loop)
        self._time_fn = time.monotonic

        # Phase: "INTRO" / "PLAY" / "DONE"
        self.phase: str = "INTRO"
        self.intro_start: float | None = None
        self.play_start: float | None = None  # aligned with MIDI 0s

        # Chart state
        self.chart_notes: List[ChartNote] = []
        self._notes_built: bool = False
        self.current_index: int = 0              # index for judge window
        self.active_note: Optional[ChartNote] = None

        # Score
        self.score: int = 0
        self.total_notes: int = 0
        self.max_score: int = 0

        # Lane mapping
        self._key_x_ranges = self._build_key_x_ranges()

        # Feedback lamps (left/right columns)
        self.feedback_until_song_time: float | None = None
        self.feedback_color: Optional[Tuple[int, int, int]] = None

        # Render optimization: skip old notes
        self.render_start_index: int = 0

        # Background audio scheduler
        self.audio_scheduler: Optional[AudioScheduler] = None

    # ---- external hooks for InputManager ----

    def stop_audio(self) -> None:
        """
        Stop background audio (scheduler thread + any ringing notes).
        Call this when leaving rhythm mode OR restarting it.
        """
        if self.audio_scheduler is not None:
            self.audio_scheduler.stop()
            try:
                self.audio_scheduler.join(timeout=0.1)
            except RuntimeError:
                # Thread never started; safe to ignore
                pass
            self.audio_scheduler = None

        if self.audio is not None:
            try:
                self.audio.stop_all()
            except Exception as e:
                if self.debug:
                    print(f"[Rhythm] stop_audio: {e}")

    def on_exit(self) -> None:
        """
        Called by InputManager when switching away from rhythm mode.
        Ensures music is stopped immediately and animation stops.
        """
        if self.debug:
            print("[Rhythm] on_exit() → stop_audio + phase=DONE")
        self.stop_audio()
        self.phase = "DONE"

    # ------------------------------------------------------------------
    # Lane mapping: key → [x0, x1)
    # ------------------------------------------------------------------

    def _build_key_x_ranges(self) -> Dict[KeyId, Tuple[int, int]]:
        """
        Split the center region of the LED matrix into len(RHYTHM_KEYS) lanes.
        x=0 and x=width-1 are reserved for feedback lights.
        """
        w = self.led.width
        if w <= 2:
            # Fallback: everything inside, if panel is too narrow
            return {k: (0, w) for k in RHYTHM_KEYS}

        inner_w = w - 2  # usable width between feedback columns
        n = len(RHYTHM_KEYS)
        base = inner_w // n
        rem = inner_w % n

        ranges: Dict[KeyId, Tuple[int, int]] = {}
        x = 1  # start at x=1, leaving x=0 for feedback
        for i, key in enumerate(RHYTHM_KEYS):
            span = base + (1 if i < rem else 0)
            x0 = x
            x1 = x + span
            ranges[key] = (x0, x1)
            x = x1

        return ranges

    def _key_x_range(self, key: KeyId) -> Tuple[int, int]:
        return self._key_x_ranges.get(key, (1, max(1, self.led.width - 1)))

    # ------------------------------------------------------------------
    # Reset / re-enter rhythm mode
    # ------------------------------------------------------------------

    def reset(self, now: float) -> None:
        """
        Called by InputManager when we switch *into* rhythm mode.
        """
        # Stop any previous audio playback & scheduler
        self.stop_audio()

        self.phase = "INTRO"
        self.intro_start = now
        self.play_start = None
        self.current_index = 0
        self.active_note = None
        self.score = 0

        if not self._notes_built:
            self._build_chart_from_midi()
            self._notes_built = True

        self._reset_notes_state()

        self.total_notes = len(self.chart_notes)
        self.max_score = self.total_notes * 2

        # Reset feedback + render index
        self.feedback_until_song_time = None
        self.feedback_color = None
        self.render_start_index = 0

        # Create a new audio scheduler (it will be started when PLAY begins)
        if self.audio is not None and self.total_notes > 0:
            self.audio_scheduler = AudioScheduler(
                self.audio, self.chart_notes, self._time_fn
            )
        else:
            self.audio_scheduler = None

        if self.debug:
            print(
                f"[Rhythm] reset: notes={self.total_notes}, "
                f"max_score={self.max_score}"
            )

    def _reset_notes_state(self) -> None:
        """
        Clear per-note runtime flags when starting a new run.
        """
        for n in self.chart_notes:
            n.hit = False
            n.judged = False
            n.score = 0

    # ------------------------------------------------------------------
    # MIDI → chart: build melody notes
    # ------------------------------------------------------------------

    def _build_chart_from_midi(self) -> None:
        """
        Parse the MIDI file and build a compressed melody chart.
        """
        try:
            mid = mido.MidiFile(self.midi_path)
        except Exception as e:
            print(f"[Rhythm] Failed to load MIDI: {self.midi_path} ({e})")
            self.chart_notes = []
            return

        ticks_per_beat = mid.ticks_per_beat
        tempo = 500000  # default 120bpm
        time_sec = 0.0

        raw_notes: List[ChartNote] = []

        # Merge all tracks into a single timeline
        merged = mido.merge_tracks(mid.tracks)

        for msg in merged:
            # Accumulate time in seconds
            if msg.time:
                dt = mido.tick2second(msg.time, ticks_per_beat, tempo)
                time_sec += dt

            if msg.is_meta and msg.type == "set_tempo":
                tempo = msg.tempo
                continue

            if msg.type == "note_on" and msg.velocity > 0:
                # skip percussion channel (9)
                channel = getattr(msg, "channel", 0)
                if channel == 9:
                    continue

                midi_note = msg.note
                velocity = msg.velocity / 127.0
                key = self._midi_note_to_key(midi_note)

                raw_notes.append(
                    ChartNote(
                        time=time_sec,
                        midi_note=midi_note,
                        key=key,
                        velocity=velocity,
                    )
                )

        raw_notes.sort(key=lambda n: n.time)

        # Compress to main melody:
        # notes within cluster_eps seconds are grouped,
        # and we keep only the highest note in that group.
        melody: List[ChartNote] = []
        if raw_notes:
            cluster: List[ChartNote] = [raw_notes[0]]
            cluster_eps = 0.08  # 80ms

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
                f"[Rhythm] MIDI parsed: raw={len(raw_notes)} → melody={len(melody)}"
            )

    def _midi_note_to_key(self, midi_note: int) -> KeyId:
        """
        Map MIDI note to one of the 5 lanes using (note - 60) mod 5.
        """
        idx = (midi_note - 60) % 5
        idx = max(0, min(4, idx))
        return KeyId(idx)

    # ------------------------------------------------------------------
    # Intro rendering: "RHYTHM GAME" then countdown 5→1 (flipped Y)
    # ------------------------------------------------------------------

    def _set_xy_flipped(self, x: int, y: int, color) -> None:
        """
        Helper that flips Y-axis so that logical y=0 is top of the panel.
        """
        h = self.led.height
        if 0 <= x < self.led.width and 0 <= y < self.led.height:
            self.led.set_xy(x, h - 1 - y, color)

    def _draw_char_flipped(self, ch: str, x0: int, y0: int, color) -> None:
        bitmap = FONT_3x5.get(ch.upper())
        if bitmap is None:
            return
        for dy, row in enumerate(bitmap):
            for dx, bit in enumerate(row):
                if bit == "1":
                    self._set_xy_flipped(x0 + dx, y0 + dy, color)

    def _draw_text_center_flipped(self, text: str, y: int, color) -> None:
        text = text.upper()
        char_w = 4  # 3 pixels + 1 spacing
        total_w = len(text) * char_w - 1
        x0 = max(0, (self.led.width - total_w) // 2)

        x = x0
        for ch in text:
            self._draw_char_flipped(ch, x, y, color)
            x += char_w

    def _render_intro(self, now: float) -> None:
        assert self.intro_start is not None
        t = now - self.intro_start

        self.led.clear_all()

        if t < INTRO_COUNTDOWN_START_SEC:
            # Show "RHYTHM GAME" only
            self._draw_text_center_flipped("RHYTHM", 2, (0, 180, 255))
            self._draw_text_center_flipped("GAME", 8, (255, 120, 0))
        else:
            # After countdown_start, show only 5→1
            remain = max(0.0, INTRO_TOTAL_SEC - t)
            step = int(remain / 0.5) + 1
            digit = min(5, max(1, step))
            self._draw_text_center_flipped(str(digit), 4, (255, 255, 255))

        self.led.show()

        if t >= INTRO_TOTAL_SEC:
            self._start_play_phase(now)

    def _start_play_phase(self, now: float) -> None:
        """
        Transition from INTRO → PLAY, and start the AudioScheduler.
        """
        self.phase = "PLAY"
        self.play_start = now
        self.current_index = 0
        self.active_note = None

        # Start audio scheduler thread now that we know play_start
        if self.audio_scheduler is not None:
            self.audio_scheduler.set_start_time(self.play_start)
            self.audio_scheduler.start()

        if self.debug:
            print("[Rhythm] INTRO finished. Start PLAY phase.")

    # ------------------------------------------------------------------
    # Hit / miss judgment and feedback
    # ------------------------------------------------------------------

    def _start_feedback(self, song_time: float, color: Tuple[int, int, int]) -> None:
        """
        Set feedback color and end time for the left/right columns.
        """
        self.feedback_color = color
        self.feedback_until_song_time = song_time + FEEDBACK_DURATION_SEC

    def _register_hit(self, note: ChartNote, dt: float, song_time: float) -> None:
        """
        dt: hit_time - note_time (seconds).
        """
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

        # Feedback color by score
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

        # Miss → red feedback
        self._start_feedback(song_time, FEEDBACK_COLOR_MISS)

        if self.debug:
            print(f"[Rhythm] MISS key={note.key}")

    # ------------------------------------------------------------------
    # Event handling: button NOTE_ON as "hit"
    # ------------------------------------------------------------------

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
            if self.active_note is None:
                continue

            note = self.active_note
            if ev.key != note.key:
                continue

            dt = song_time - note.time
            self._register_hit(note, dt, song_time)
            # We don't clear active_note here; _update_active_note will handle it.

    # ------------------------------------------------------------------
    # Main update (called each frame by InputManager)
    # ------------------------------------------------------------------

    def update(self, now: float) -> None:
        if self.phase == "INTRO":
            self._render_intro(now)
            return

        if self.phase == "DONE":
            self._render_result()
            return

        # PLAY phase
        if self.play_start is None:
            self.play_start = now

        song_time = now - self.play_start

        # 1) Update active note: check for miss
        self._update_active_note(song_time)

        # 2) Slide render_start_index so we skip old notes
        self._update_render_start_index(song_time)

        # 3) If there is no active note, see if the next note should enter the judge window
        self._spawn_next_note_if_needed(song_time)

        # 4) Render falling blocks + feedback
        self._render_play(song_time)

        # 5) If all notes are judged, go to DONE
        self._check_done_and_finish()

    def _update_active_note(self, song_time: float) -> None:
        if self.active_note is None:
            return

        note = self.active_note
        dt = song_time - note.time

        if dt > MISS_LATE_SEC:
            if not note.judged:
                self._register_miss(note, song_time)
            self.active_note = None

    def _update_render_start_index(self, song_time: float) -> None:
        """
        Advance render_start_index so we don't iterate over very old notes.
        """
        cutoff_time = song_time - (FALL_DURATION_SEC + MISS_LATE_SEC)
        while (
            self.render_start_index < len(self.chart_notes)
            and self.chart_notes[self.render_start_index].time < cutoff_time
        ):
            self.render_start_index += 1

    def _spawn_next_note_if_needed(self, song_time: float) -> None:
        """
        Bring the next note into the "active/judge" window a little bit
        before its target time, so user can hit it slightly early.
        """
        if self.active_note is not None:
            return
        if self.current_index >= len(self.chart_notes):
            return

        note = self.chart_notes[self.current_index]
        appear_lead = 0.2  # seconds before note.time to become hittable

        if song_time >= note.time - appear_lead:
            self.active_note = note
            self.current_index += 1

            if self.debug:
                print(
                    f"[Rhythm] SPAWN note key={note.key} t={note.time:.3f} "
                    f"song_t={song_time:.3f}"
                )

    def _check_done_and_finish(self) -> None:
        """
        When all notes are judged, switch to DONE and stop audio.
        """
        if self.current_index < len(self.chart_notes):
            return
        if self.active_note is not None:
            return

        all_judged = all(n.judged for n in self.chart_notes)
        if not all_judged:
            return

        self.phase = "DONE"
        self.stop_audio()
        if self.debug:
            print(
                f"[Rhythm] DONE. score={self.score}/{self.max_score} "
                f"(notes={self.total_notes})"
            )

    # ------------------------------------------------------------------
    # Rendering: falling blocks + feedback columns
    # ------------------------------------------------------------------

    def _compute_fall_progress(self, note: ChartNote, song_time: float) -> Optional[float]:
        """
        Compute falling progress in [0,1], or None if the note
        should not be rendered at this song_time.
        """
        dt_to_note = note.time - song_time

        # Not yet within falling window → all later notes also not
        if dt_to_note > FALL_DURATION_SEC:
            return None

        # Too far in the past → skip
        if dt_to_note < -MISS_LATE_SEC:
            return None

        # dt_to_note >= 0: still falling
        if dt_to_note >= 0:
            t_from_start = FALL_DURATION_SEC - dt_to_note
            progress = t_from_start / FALL_DURATION_SEC
        else:
            # just after target time: treat as fully fallen
            progress = 1.0

        return max(0.0, min(1.0, progress))

    def _compute_note_color(self, note: ChartNote, progress: float) -> Tuple[int, int, int]:
        """
        Decide the RGB color of a falling block for this note.
        """
        if note.hit:
            base_color = (255, 255, 255)
            boost = 1.0
        else:
            base_color = LANE_COLORS.get(note.key, (0, 180, 255))
            if self.active_note is not None and note is self.active_note:
                boost = 1.1
            else:
                boost = 0.8

        # Slightly brighten as it falls down
        brightness_factor = math.sqrt(progress) * boost
        brightness_factor = max(0.3, min(1.0, brightness_factor))

        r = int(base_color[0] * brightness_factor)
        g = int(base_color[1] * brightness_factor)
        b = int(base_color[2] * brightness_factor)
        return (r, g, b)

    def _render_play(self, song_time: float) -> None:
        self.led.clear_all()

        w = self.led.width
        h = self.led.height

        # Draw falling blocks in the center lanes
        for note in self.chart_notes[self.render_start_index:]:
            progress = self._compute_fall_progress(note, song_time)
            if progress is None:
                if note.time - song_time > FALL_DURATION_SEC:
                    break
                continue

            # progress=0 → y near top (h-1)
            # progress=1 → y near bottom (0)
            y_center = int((1.0 - progress) * (h - 1) + 0.5)

            color = self._compute_note_color(note, progress)
            x0, x1 = self._key_x_range(note.key)

            # Height = 3 cells: center ±1
            for x in range(x0, x1):
                for y in range(y_center - 1, y_center + 2):
                    if 0 <= y < h:
                        self.led.set_xy(x, y, color)

        # Draw left/right feedback columns
        if (
            self.feedback_color is not None
            and self.feedback_until_song_time is not None
            and self.play_start is not None
        ):
            if (song_time <= self.feedback_until_song_time):
                left_x = 0
                right_x = w - 1
                for y in range(h):
                    self.led.set_xy(left_x, y, self.feedback_color)
                    self.led.set_xy(right_x, y, self.feedback_color)

        self.led.show()

    # ------------------------------------------------------------------
    # DONE screen: "score/max_score"
    # ------------------------------------------------------------------

    def _render_result(self) -> None:
        self.led.clear_all()
        text = f"{self.score}/{self.max_score}"
        self._draw_text_center_flipped(text, 5, (255, 255, 255))
        self.led.show()
