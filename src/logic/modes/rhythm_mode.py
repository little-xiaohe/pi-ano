# src/logic/modes/rhythm_mode.py

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional

import mido

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.config.keys import KeyId
from src.logic.input_event import InputEvent, EventType
from src.hardware.audio.audio_engine import AudioEngine

# 你可以換成自己的 MIDI 檔（目前是小星星）
DEFAULT_MIDI_PATH = (
    "/home/pi/pi-ano/src/hardware/audio/assets/midi/Lemon.mid"
)

# Rhythm mode 只用前 5 顆 key（0..4）
RHYTHM_KEYS: List[KeyId] = [
    KeyId.KEY_0,
    KeyId.KEY_1,
    KeyId.KEY_2,
    KeyId.KEY_3,
    KeyId.KEY_4,
]

# 每條軌道的基礎顏色（未命中狀態）
LANE_COLORS = {
    KeyId.KEY_0: (255, 120, 120),   # 紅
    KeyId.KEY_1: (255, 210, 120),   # 橘黃
    KeyId.KEY_2: (120, 220, 255),   # 淺藍
    KeyId.KEY_3: (160, 200, 255),   # 藍偏紫
    KeyId.KEY_4: (210, 160, 255),   # 紫
}

# 判定燈顏色
FEEDBACK_COLOR_PERFECT = (0, 255, 120)   # 綠色（2分）
FEEDBACK_COLOR_GOOD    = (255, 180, 60)  # 橘色（1分）
FEEDBACK_COLOR_MISS    = (255, 60, 60)   # 紅色（miss）


# ---------------------------------------------------------------------------
# ChartNote: 一顆節奏 note（主旋律壓縮後的單一 note）
# ---------------------------------------------------------------------------

@dataclass
class ChartNote:
    time: float                 # 秒數（相對整首歌開始，主旋律時間）
    midi_note: int              # MIDI note number
    key: KeyId                  # 映射到哪一個 LED key (0..4)
    velocity: float             # 0.0~1.0
    hit: bool = False           # 有沒有被成功打到
    judged: bool = False        # 是否已經判定（hit 或 miss）
    score: int = 0              # 0, 1, or 2 分
    audio_started: bool = False # 聲音是否已經播放（只決定 note_on_midi）


# ---------------------------------------------------------------------------
# 簡單 3x5 字型，用於 INTRO / 倒數 / 結果（翻轉版）
# ---------------------------------------------------------------------------

FONT_3x5 = {
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
# RhythmMode 本體
# ---------------------------------------------------------------------------

class RhythmMode:
    """
    Rhythm game mode.

    - 用同一首 MIDI 檔當「主旋律」來源。
    - 解析所有 note，依時間做 clustering，只留下每一拍的「最高音」當作主旋律。
    - 顯示方式：
        每個 note 在要按之前的一段時間內，會以「三格高的方塊」從上往下掉在中間 5 軌。
        最左 & 最右一列保留當判定燈（紅 / 綠 / 橘），不畫音符。
    - 遊戲流程：
        1) INTRO：顯示 RHYTHM / GAME，接著只顯示 5,4,3,2,1 倒數
        2) PLAY：note 往下掉，到達底部時為判定時間 & 播主旋律音
        3) DONE：LED 顯示「score/max_score」
    """

    def __init__(
        self,
        led: LedMatrix,
        audio: Optional[AudioEngine] = None,
        midi_path: str = DEFAULT_MIDI_PATH,
        debug: bool = False,
    ) -> None:
        self.led = led
        self.audio = audio
        self.midi_path = midi_path
        self.debug = debug

        # Time function（和 main 用同一種 monotonic）
        self._time_fn = time.monotonic

        # 遊戲階段：INTRO / PLAY / DONE
        self.phase: str = "INTRO"
        self.intro_start: float | None = None
        self.play_start: float | None = None  # 真正開始對齊 MIDI 的時間

        # INTRO 參數
        self.intro_total = 4.0      # 前 4 秒：顯示字 + 倒數
        self.countdown_start = 1.5  # 1.5 秒後開始 5→1 倒數

        # Chart notes
        self.chart_notes: List[ChartNote] = []
        self._notes_built: bool = False
        self.current_index: int = 0         # 下一顆 note index（進入判定用）
        self.active_note: Optional[ChartNote] = None  # 正在被判定的那顆

        # 判定窗口（秒）
        self.perfect_window = 0.08   # |Δt| <= 80ms → 2 分
        self.good_window = 0.16      # |Δt| <= 160ms → 1 分
        self.miss_late_window = 0.25 # 超過這個就當 miss（不關音，只標記）

        # note 掉落時間：音符會在 time - fall_duration 時出現在最上方
        # 然後在 time 時剛好掉到最底
        self.fall_duration = 1.0     # 秒

        # 分數
        self.score: int = 0
        self.total_notes: int = 0
        self.max_score: int = 0

        # key → x_range 映射（用「中間區域」平均切成 5 軌）
        self._key_x_ranges = self._build_key_x_ranges()

        # 判定燈（左右兩列）狀態：用 song_time 來計時
        self.feedback_until_song_time: float | None = None
        self.feedback_color: Optional[tuple[int, int, int]] = None
        self.feedback_duration: float = 0.25  # 秒

    # ------------------------------------------------------------------
    # key → x-range 映射（掉落格子的寬度）
    # ------------------------------------------------------------------
    def _build_key_x_ranges(self) -> dict[KeyId, tuple[int, int]]:
        """
        將「螢幕中間區域」平均切成 len(RHYTHM_KEYS) 軌，
        最左 (x=0) & 最右 (x=width-1) 保留給判定燈。
        """
        w = self.led.width
        if w <= 2:
            # 太窄就全部塞在中間（理論上不會發生）
            return {k: (0, w) for k in RHYTHM_KEYS}

        inner_w = w - 2  # 中間可用寬度
        n = len(RHYTHM_KEYS)
        base = inner_w // n
        rem = inner_w % n

        ranges: dict[KeyId, tuple[int, int]] = {}
        x = 1  # 從 x=1 開始，保留 x=0；最後一格自然不超過 w-2
        for i, key in enumerate(RHYTHM_KEYS):
            span = base + (1 if i < rem else 0)
            x0 = x
            x1 = x + span
            ranges[key] = (x0, x1)
            x = x1

        return ranges

    def _key_x_range(self, key: KeyId) -> tuple[int, int]:
        return self._key_x_ranges.get(key, (1, max(1, self.led.width - 1)))

    # ------------------------------------------------------------------
    # Reset / 初始化遊戲狀態（切進 rhythm mode 時由 InputManager 呼叫）
    # ------------------------------------------------------------------
    def reset(self, now: float) -> None:
        self.phase = "INTRO"
        self.intro_start = now
        self.play_start = None
        self.current_index = 0
        self.active_note = None
        self.score = 0

        if not self._notes_built:
            self._build_chart_from_midi()
            self._notes_built = True

        # 每次重新開始要把所有 note 狀態清乾淨
        for n in self.chart_notes:
            n.hit = False
            n.judged = False
            n.score = 0
            n.audio_started = False

        self.total_notes = len(self.chart_notes)
        self.max_score = self.total_notes * 2

        # 重設判定燈
        self.feedback_until_song_time = None
        self.feedback_color = None

        if self.debug:
            print(
                f"[Rhythm] reset: notes={self.total_notes}, "
                f"max_score={self.max_score}"
            )

    # ------------------------------------------------------------------
    # MIDI → chart：只取主旋律（同一時間群組只留最高音）
    # ------------------------------------------------------------------
    def _build_chart_from_midi(self) -> None:
        try:
            mid = mido.MidiFile(self.midi_path)
        except Exception as e:
            # print(f"[Rhythm] Failed to load MIDI: {self.midi_path} ({e})")
            self.chart_notes = []
            return

        ticks_per_beat = mid.ticks_per_beat
        tempo = 500000  # default 120bpm
        time_sec = 0.0

        raw_notes: List[ChartNote] = []

        # 先 merge 所有 tracks，把整首歌當一條時間軸
        merged = mido.merge_tracks(mid.tracks)

        for msg in merged:
            # 先把 delta ticks 轉成秒，累積起來
            if msg.time:
                dt = mido.tick2second(msg.time, ticks_per_beat, tempo)
                time_sec += dt

            if msg.is_meta and msg.type == "set_tempo":
                tempo = msg.tempo
                continue

            if msg.type == "note_on" and msg.velocity > 0:
                # 過濾 percussion channel（9 = drums）
                channel = getattr(msg, "channel", 0)
                if channel == 9:
                    continue

                midi_note = msg.note
                velocity = msg.velocity / 127.0

                # 簡單 mapping：把 MIDI note 對應到 5 個 key
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

        # 壓縮成主旋律：把「時間很接近」的多顆 note 視為同一拍，只取最高音
        melody: List[ChartNote] = []
        if raw_notes:
            cluster: List[ChartNote] = [raw_notes[0]]
            cluster_eps = 0.08  # 80ms 以內視為同一個 time group

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
        把 MIDI note 簡單 map 到 5 個 key（0..4）。

        做法：以 C4=60 為基準，取 (note - 60) mod 5。
        """
        idx = (midi_note - 60) % 5
        idx = max(0, min(4, idx))
        return KeyId(idx)

    # ------------------------------------------------------------------
    # Intro 畫面：RHYTHM GAME + 5 4 3 2 1 倒數（Y 軸翻轉）
    # ------------------------------------------------------------------
    def _set_xy_flipped(self, x: int, y: int, color) -> None:
        """
        把 y 軸翻轉（0 在邏輯最上方 → 實際最下方）。
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

        # 0.0 ~ 1.5 秒：顯示 "RHYTHM GAME"
        if t < self.countdown_start:
            self._draw_text_center_flipped("RHYTHM", 2, (0, 180, 255))
            self._draw_text_center_flipped("GAME", 8, (255, 120, 0))
        else:
            # 1.5 秒之後：只顯示 5→1 倒數
            remain = max(0.0, self.intro_total - t)
            step = int(remain / 0.5) + 1
            digit = min(5, max(1, step))
            self._draw_text_center_flipped(str(digit), 4, (255, 255, 255))

        self.led.show()

        if t >= self.intro_total:
            self.phase = "PLAY"
            self.play_start = now
            self.current_index = 0
            self.active_note = None
            if self.debug:
                print("[Rhythm] INTRO finished. Start PLAY phase.")

    # ------------------------------------------------------------------
    # Hit 判定 & 分數（不再發出 hit 音效）
    # ------------------------------------------------------------------
    def _start_feedback(self, song_time: float, color: tuple[int, int, int]) -> None:
        """設定左右判定燈的顯示顏色與結束時間。"""
        self.feedback_color = color
        self.feedback_until_song_time = song_time + self.feedback_duration

    def _register_hit(self, note: ChartNote, dt: float, song_time: float) -> None:
        """
        dt: hit_time - note_time（秒）
        """
        if note.judged:
            return

        note.judged = True
        note.hit = True

        adt = abs(dt)
        if adt <= self.perfect_window:
            note.score = 2
        elif adt <= self.good_window:
            note.score = 1
        else:
            note.score = 0

        if note.score > 0:
            self.score += note.score

        # 根據分數決定判定燈顏色
        if note.score == 2:
            self._start_feedback(song_time, FEEDBACK_COLOR_PERFECT)
        elif note.score == 1:
            self._start_feedback(song_time, FEEDBACK_COLOR_GOOD)
        # 0 分就不觸發判定燈（hit 但判為 too late）

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

        # miss → 左右兩排紅色
        self._start_feedback(song_time, FEEDBACK_COLOR_MISS)

        if self.debug:
            print(f"[Rhythm] MISS key={note.key}")

    # ------------------------------------------------------------------
    # handle_events: 只吃 NOTE_ON（button 按下）
    # ！！這版不再清掉 active_note，讓音樂仍然能在 note.time 播出！！
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
            # 不在這裡清掉 active_note，交給 _update_active_note

    # ------------------------------------------------------------------
    # update: 根據 phase 決定畫面 & 播放（每 frame 由 InputManager 呼叫）
    # ------------------------------------------------------------------
    def update(self, now: float) -> None:
        if self.phase == "INTRO":
            self._render_intro(now)
            return

        if self.phase == "DONE":
            self._render_result(now)
            return

        # PLAY phase
        if self.play_start is None:
            self.play_start = now

        song_time = now - self.play_start

        # 1) 控制 active_note 的生命週期（負責時間到時播音 + 超時清掉）
        self._update_active_note(song_time)

        # 2) 如果沒有 active_note，就看下一顆 note 要不要進入「判定狀態」
        self._spawn_next_note_if_needed(song_time)

        # 3) 畫目前的狀態：所有正在掉落/可判定的 note 都畫成「三格方塊」
        self._render_play(song_time)

        # 4) 如果所有 note 都已經被判定（hit 或 miss），就進 DONE
        if self.current_index >= len(self.chart_notes) and self.active_note is None:
            all_judged = all(n.judged for n in self.chart_notes)
            if all_judged:
                self.phase = "DONE"
                if self.debug:
                    print(
                        f"[Rhythm] DONE. score={self.score}/{self.max_score} "
                        f"(notes={self.total_notes})"
                    )

    def _update_active_note(self, song_time: float) -> None:
        if self.active_note is None:
            return

        note = self.active_note

        # 到 note.time 時，一定播主旋律（不管有沒有先被 hit）
        if self.audio is not None and (not note.audio_started):
            if song_time >= note.time:
                vel = int(max(0.1, min(1.0, note.velocity)) * 127)
                self.audio.note_on_midi(note.midi_note, vel)
                note.audio_started = True

        # 當時間超過 miss_late_window：
        # - 如果還沒判定過 → 算 miss（會觸發紅色判定燈）
        # - 不關音，只把 active_note 清掉，讓下一顆登場
        dt = song_time - note.time
        if dt > self.miss_late_window:
            if not note.judged:
                self._register_miss(note, song_time)
            self.active_note = None

    def _spawn_next_note_if_needed(self, song_time: float) -> None:
        if self.active_note is not None:
            return
        if self.current_index >= len(self.chart_notes):
            return

        note = self.chart_notes[self.current_index]
        appear_lead = 0.2  # 提前 200ms 進入判定狀態 / 可 hit

        if song_time >= note.time - appear_lead:
            self.active_note = note
            self.current_index += 1

            if self.debug:
                print(
                    f"[Rhythm] SPAWN note key={note.key} t={note.time:.3f} "
                    f"song_t={song_time:.3f}"
                )

    # ------------------------------------------------------------------
    # 由上往下掉的「方塊」，高度 3 排（多顆同時顯示）
    # 每條軌顏色不同；命中後變白；左右兩排做判定燈
    # ------------------------------------------------------------------
    def _render_play(self, song_time: float) -> None:
        self.led.clear_all()

        w = self.led.width
        h = self.led.height

        # 先畫中間 5 軌的掉落方塊
        for note in self.chart_notes:
            dt_to_note = note.time - song_time

            # 還沒出現的 note
            if dt_to_note > self.fall_duration:
                break

            # 太久以前的 note（miss window 也過了）→ 不畫
            if dt_to_note < -self.miss_late_window:
                continue

            # 時間 → 掉落進度 progress
            if dt_to_note >= 0:
                t_from_start = self.fall_duration - dt_to_note
                progress = t_from_start / self.fall_duration
            else:
                progress = 1.0

            progress = max(0.0, min(1.0, progress))

            # progress = 0 → y = 最上面 (h-1)
            # progress = 1 → y = 最下面 (0)
            y_center = int((1.0 - progress) * (h - 1) + 0.5)

            # 顏色邏輯：
            # 1) 命中了 → 方塊變白
            if note.hit:
                base_color = (255, 255, 255)
                boost = 1.0
            else:
                # 先取該軌道的基本顏色
                base_color = LANE_COLORS.get(note.key, (0, 180, 255))

                # 2) 還沒 hit，且是目前 active note：稍微亮一點
                if self.active_note is not None and note is self.active_note:
                    boost = 1.1
                # 3) 其他掉落 note：一般亮度
                else:
                    boost = 0.8

            brightness_factor = math.sqrt(progress) * boost
            brightness_factor = max(0.3, min(1.0, brightness_factor))

            r = int(base_color[0] * brightness_factor)
            g = int(base_color[1] * brightness_factor)
            b = int(base_color[2] * brightness_factor)
            color = (r, g, b)

            x0, x1 = self._key_x_range(note.key)

            # 高度三排：以 y_center 為中心，上下一格
            for x in range(x0, x1):
                for y in range(y_center - 1, y_center + 2):
                    if 0 <= y < h:
                        self.led.set_xy(x, y, color)

        # 再畫左右判定燈（不影響中間方塊）
        if (
            self.feedback_color is not None
            and self.feedback_until_song_time is not None
            and song_time <= self.feedback_until_song_time
        ):
            left_x = 0
            right_x = w - 1
            for y in range(h):
                self.led.set_xy(left_x, y, self.feedback_color)
                self.led.set_xy(right_x, y, self.feedback_color)

        self.led.show()

    # ------------------------------------------------------------------
    # DONE 畫面：顯示「score/max_score」
    # ------------------------------------------------------------------
    def _render_result(self, now: float) -> None:
        self.led.clear_all()

        text = f"{self.score}/{self.max_score}"
        self._draw_text_center_flipped(text, 5, (255, 255, 255))

        self.led.show()
