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

# 3 個難度對應的 MIDI 檔
DEFAULT_MIDI_PATHS: Dict[str, str] = {
    "easy":   "/home/pi/pi-ano/src/hardware/audio/assets/midi/rhythm/twinkle-twinkle-little-star.mid",
    "medium": "/home/pi/pi-ano/src/hardware/audio/assets/midi/rhythm/The_Pink_Panther.mid",
    "hard":   "/home/pi/pi-ano/src/hardware/audio/assets/midi/rhythm/Cant_Help_Falling_In_Love.mid",
}

# Rhythm mode uses the first 5 keys (0..4)
RHYTHM_KEYS: List[KeyId] = [
    KeyId.KEY_0,
    KeyId.KEY_1,
    KeyId.KEY_2,
    KeyId.KEY_3,
    KeyId.KEY_4,
]

# 高彩度 lane 顏色（遊戲中的落下方塊用）
LANE_COLORS: Dict[KeyId, Tuple[int, int, int]] = {
    KeyId.KEY_0: (255, 50, 50),     # Electric Red（亮但不橘）
    KeyId.KEY_1: (255, 120, 0),     # Vivid Orange（純橘，不偏黃）
    KeyId.KEY_2: (0, 180, 255),     # Neon Cyan（乾淨的電光藍）
    KeyId.KEY_3: (150, 80, 255),    # Electric Purple（亮紫、辨識度高）
    KeyId.KEY_4: (255, 0, 170),     # Hot Magenta（節奏遊戲經典亮粉紫）
}


# ★ 選難度時用的三個 key 顏色（Pi 大 LED 上顯示）
#   KEY_1 → HARD (紅)
#   KEY_2 → MEDIUM (橘)
#   KEY_3 → EASY (綠)
DIFFICULTY_SELECTION_COLORS: Dict[KeyId, Tuple[int, int, int]] = {
    KeyId.KEY_1: (255, 0, 0),     # HARD → red
    KeyId.KEY_2: (255, 255, 0),   # MEDIUM → yellowish orange
    KeyId.KEY_3: (0, 200, 0),     # EASY → green (matcha-ish)
}

# Feedback colors (left/right columns)
FEEDBACK_COLOR_PERFECT = (0, 255, 120)     # neon green
FEEDBACK_COLOR_GOOD    = (255, 160, 0)     # golden orange
FEEDBACK_COLOR_MISS    = (255, 0, 0)       # pure red (強烈錯誤提示)

# Judge windows (seconds)
PERFECT_WINDOW_SEC = 0.08    # |dt| <= 80ms → 2 points
GOOD_WINDOW_SEC    = 0.16    # |dt| <= 160ms → 1 point
MISS_LATE_SEC      = 0.25    # later than this → miss

# Falling time: note appears at top at (time - FALL_DURATION_SEC),
# and reaches bottom exactly at ChartNote.time.
FALL_DURATION_SEC = 1.0

# Feedback lamp duration
FEEDBACK_DURATION_SEC = 0.25

# ★ 倒數結束後的前導時間
#   - LEAD_IN_SEC 時間內畫面先空白 / 只看到 note 從最上面慢慢掉下來
#   - 第一顆 note 會在倒數結束後「先從頂端掉 1 秒」才到判定線，同時出聲
LEAD_IN_SEC = 1.0

# ★ 最後一顆 note 結束後再多停留的時間
#   - 用來控制「音樂結束後停個幾秒」再開始 post-game 流程
TAIL_HOLD_SEC = 4.0


# ---------------------------------------------------------------------------
# RhythmMode
# ---------------------------------------------------------------------------

class RhythmMode:
    """
    Rhythm game mode driven by an external countdown (Pico), with
    three difficulties (easy / medium / hard), each using a different MIDI.

    Flow:
      1) InputManager switches to rhythm mode → reset(now)
         - phase = "WAIT_COUNTDOWN"
         - Pi LED matrix 顯示三條彩色 key（紅=HARD / 橘=MEDIUM / 綠=EASY）
         - Pico 顯示 RYTHM / SELECT MODE / 等待玩家按 D15 / D18 / D24
         - 按鍵選好難度後，InputManager 呼叫:
             rhythm.set_difficulty("easy" | "medium" | "hard")
             pico_display.send_rhythm_countdown()
         - Pico 倒數 5→1，結束時在 USB serial 印出
             RHYTHM:COUNTDOWN_DONE

      2) Pi 端收到 RHYTHM:COUNTDOWN_DONE → 呼叫:
             rhythm.start_play_after_countdown(now)
             pico_display.send_rhythm_level(difficulty)
         - phase = "PLAY"
         - AudioScheduler starts, notes begin to fall

      3) 當所有 notes 判定完成後：
         - 等待「最後一顆 note 的時間 + TAIL_HOLD_SEC」
         - phase = "DONE"
         - Pi LED 清空，音樂尾巴自然結束（不強制 stop_all）
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

        # Time function (shared with main loop)
        self._time_fn = time.monotonic

        # Difficulty → midi_path
        self.midi_paths: Dict[str, str] = midi_paths or DEFAULT_MIDI_PATHS.copy()

        # Current difficulty ("easy" / "medium" / "hard")
        self.difficulty: str = "easy"
        self.midi_path: str = self.midi_paths[self.difficulty]

        # Phase: "WAIT_COUNTDOWN" / "PLAY" / "DONE"
        self.phase: str = "WAIT_COUNTDOWN"
        self.play_start: float | None = None  # aligned with MIDI 0s (with LEAD_IN_SEC offset)

        # Chart state
        self.chart_notes: List[ChartNote] = []
        self._notes_built: bool = False

        # per-lane miss 檢查用的 index（時間序）
        self._miss_index: int = 0

        # Score (logic only; final text shown on Pico)
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

    # ------------------------------------------------------------------
    # External hooks for InputManager
    # ------------------------------------------------------------------

    def stop_audio(self) -> None:
        """
        Stop background audio scheduler thread.
        不在這裡呼叫 audio.stop_all()，避免把尾音硬切掉。
        真正要全停交給 mode 切換或程式離開時再做。
        """
        if self.audio_scheduler is not None:
            self.audio_scheduler.stop()
            try:
                self.audio_scheduler.join(timeout=0.1)
            except RuntimeError:
                # Thread never started; safe to ignore
                pass
            self.audio_scheduler = None

        if self.debug:
            print("[Rhythm] stop_audio(): scheduler stopped (no stop_all)")

    def on_exit(self) -> None:
        """
        Called by InputManager when switching away from rhythm mode.
        Ensures music is stopped immediately and LEDs are cleared.
        """
        if self.debug:
            print("[Rhythm] on_exit() → stop_audio + phase=DONE")
        self.stop_audio()
        self.phase = "DONE"
        self.led.clear_all()
        self.led.show()

    def reset(self, now: float) -> None:
        """
        Called by InputManager when we switch *into* rhythm mode.

        After reset():
          - phase = "WAIT_COUNTDOWN"
          - Pi LEDs 顯示紅/橘/綠三條（選難度）
        """
        # Stop any previous audio playback & scheduler
        self.stop_audio()

        self.phase = "WAIT_COUNTDOWN"
        self.play_start = None
        self.score = 0

        # Build chart for current difficulty
        self._notes_built = False
        self._build_chart_from_midi()
        self._reset_notes_state()

        self.total_notes = len(self.chart_notes)
        self.max_score = self.total_notes * 2

        # Reset feedback + render index + miss index
        self.feedback_until_song_time = None
        self.feedback_color = None
        self.render_start_index = 0
        self._miss_index = 0

        # Create a new audio scheduler (it will be started when PLAY begins)
        if self.audio is not None and self.total_notes > 0:
            self.audio_scheduler = AudioScheduler(
                self.audio, self.chart_notes, self._time_fn
            )
        else:
            self.audio_scheduler = None

        # 進入 WAIT_COUNTDOWN：Pi LED 用 _render_wait_countdown 畫三條彩色 key
        self._render_wait_countdown()

        if self.debug:
            print(
                f"[Rhythm] reset: phase=WAIT_COUNTDOWN, "
                f"difficulty={self.difficulty}, midi={self.midi_path}, "
                f"notes={self.total_notes}, max_score={self.max_score}"
            )

    def start_play_after_countdown(self, now: float) -> None:
        """
        Called by InputManager when Pico reports RHYTHM:COUNTDOWN_DONE.

        ★ 這裡加入 LEAD_IN_SEC：
            - 真正的 play_start = now + LEAD_IN_SEC
            - AudioScheduler 也是用同一個 start_time
            - 第一顆 note 會從頂端掉 1 秒才到判定線，同步出聲
        """
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

        # Start audio scheduler thread with the same start time
        if self.audio_scheduler is not None:
            self.audio_scheduler.set_start_time(self.play_start)
            self.audio_scheduler.start()

        if self.debug:
            print(f"[Rhythm] PLAY will start at t={self.play_start:.3f} (lead_in={LEAD_IN_SEC}s)")

    def set_difficulty(self, difficulty: str) -> None:
        """
        Change difficulty to "easy" / "medium" / "hard".
        """
        diff = difficulty.lower()
        if diff not in self.midi_paths:
            if self.debug:
                print(f"[Rhythm] set_difficulty: unknown '{difficulty}'")
            return

        self.difficulty = diff
        self.midi_path = self.midi_paths[diff]

        if self.debug:
            print(f"[Rhythm] set_difficulty -> {self.difficulty}, midi={self.midi_path}")

        # Rebuild chart for new MIDI
        self.stop_audio()  # stop any existing scheduler/notes
        self._notes_built = False
        self._build_chart_from_midi()
        self._reset_notes_state()

        self.total_notes = len(self.chart_notes)
        self.max_score = self.total_notes * 2
        self.render_start_index = 0
        self.feedback_color = None
        self.feedback_until_song_time = None
        self._miss_index = 0

        # Recreate scheduler for new chart (will start at PLAY)
        if self.audio is not None and self.total_notes > 0:
            self.audio_scheduler = AudioScheduler(
                self.audio, self.chart_notes, self._time_fn
            )
        else:
            self.audio_scheduler = None

        # 難度改好後，重新畫一次選難度的彩色鍵
        if self.phase == "WAIT_COUNTDOWN":
            self._render_wait_countdown()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reset_notes_state(self) -> None:
        """Clear per-note runtime flags when starting a new run."""
        for n in self.chart_notes:
            n.hit = False
            n.judged = False
            n.score = 0

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
                f"[Rhythm] MIDI parsed ({self.difficulty}): "
                f"raw={len(raw_notes)} → melody={len(melody)}"
            )

    def _midi_note_to_key(self, midi_note: int) -> KeyId:
        """
        Map MIDI note to one of the 5 lanes using (note - 60) mod 5.
        """
        idx = (midi_note - 60) % 5
        idx = max(0, min(4, idx))
        return KeyId(idx)

    # ------------------------------------------------------------------
    # Hit / miss judgment and feedback（per-lane）
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

    # 專門處理「沒被打到的 note → 變成 miss」
    def _update_miss_judgements(self, song_time: float) -> None:
        """
        依照時間序，把「時間已經超過 note.time + MISS_LATE_SEC」但尚未判定的 note
        標記成 miss。用 self._miss_index 讓掃描是 O(1) 漸進。
        """
        while self._miss_index < len(self.chart_notes):
            note = self.chart_notes[self._miss_index]
            # 如果這顆 note 的「判定線 + MISS_LATE_SEC」還沒到，就先停在這裡
            if song_time < note.time + MISS_LATE_SEC:
                break

            # 時間已經超過了 → 如果還沒判定，就當作 miss
            if not note.judged:
                self._register_miss(note, song_time)

            self._miss_index += 1

    # ------------------------------------------------------------------
    # Event handling: per-lane hit 判定
    # ------------------------------------------------------------------

    def handle_events(self, events: List[InputEvent]) -> None:
        # Only accept hits during PLAY
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

            # 在這條 lane 上，找「時間最接近、尚未判定、且 |dt| <= MISS_LATE_SEC」的 note
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
    # Main update (called each frame by InputManager)
    # ------------------------------------------------------------------

    def update(self, now: float) -> None:
        if self.phase == "WAIT_COUNTDOWN":
            # 選難度階段 Pi LED 顯示三條彩色 key
            self._render_wait_countdown()
            return

        if self.phase == "DONE":
            # Keep LEDs off; final score is shown on Pico.
            self.led.clear_all()
            self.led.show()
            return

        # PLAY phase
        if self.play_start is None:
            # 理論上不會發生，保底處理
            self.play_start = now

        song_time = now - self.play_start

        # 1) 先把「時間已經過頭但沒被打到」的 note 標成 miss
        self._update_miss_judgements(song_time)

        # 2) Slide render_start_index so we skip old notes
        self._update_render_start_index(song_time)

        # 3) Render falling blocks + feedback
        self._render_play(song_time)

        # 4) If all notes are judged, maybe go to DONE (with tail hold)
        self._check_done_and_finish(song_time)

    # ------------------------------------------------------------------
    # WAIT_COUNTDOWN rendering: three colored lanes
    # ------------------------------------------------------------------

    def _render_wait_countdown(self) -> None:
        """
        WAIT_COUNTDOWN 階段：
          - 不顯示 falling notes
          - 顯示三個對應難度的彩色鍵：
              KEY_1 (HARD)   → 紅
              KEY_2 (MEDIUM) → 橘
              KEY_3 (EASY)   → 綠
        """
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
        """
        Advance render_start_index so we don't iterate over very old notes.
        """
        cutoff_time = song_time - (FALL_DURATION_SEC + MISS_LATE_SEC)
        while (
            self.render_start_index < len(self.chart_notes)
            and self.chart_notes[self.render_start_index].time < cutoff_time
        ):
            self.render_start_index += 1

    # 5) If all notes are judged, maybe go to DONE (with tail hold)
    def _check_done_and_finish(self, song_time: float) -> None:
        """
        When all notes are judged, switch to DONE after TAIL_HOLD_SEC
        past the last note time.
        不在這裡停音，讓最後一顆 note 自然收尾。
        """
        if not self.chart_notes:
            return

        # 還有沒判完的 note → 還不能 DONE
        if not all(n.judged for n in self.chart_notes):
            return

        last_time = self.chart_notes[-1].time
        if song_time < last_time + TAIL_HOLD_SEC:
            return

        # 只改 phase & LED，不呼叫 stop_audio / stop_all()
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

    def _compute_note_color(self, note: ChartNote, progress: float, song_time: float) -> Tuple[int, int, int]:
        """
        Decide the RGB color of a falling block for this note.
        """
        if note.hit:
            base_color = (255, 255, 255)
            boost = 1.0
        else:
            base_color = LANE_COLORS.get(note.key, (0, 180, 255))
            # 接近判定時間的 note 稍微亮一點
            if abs(song_time - note.time) <= GOOD_WINDOW_SEC:
                boost = 1.1
            else:
                boost = 0.9

        # Brighten as it falls down
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

            color = self._compute_note_color(note, progress, song_time)
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
            if song_time <= self.feedback_until_song_time:
                left_x = 0
                right_x = w - 1
                for y in range(h):
                    self.led.set_xy(left_x, y, self.feedback_color)
                    self.led.set_xy(right_x, y, self.feedback_color)

        self.led.show()
