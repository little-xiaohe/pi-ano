# src/logic/modes/rhythm_mode.py

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional

import mido

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.config.keys import KeyId
from src.logic.input_event import InputEvent, EventType
from src.hardware.audio.audio_engine import AudioEngine

# 你可以換成自己的 MIDI 檔
DEFAULT_MIDI_PATH = (
    "/home/pi/pi-ano/src/hardware/audio/assets/midi/Merry_christmas_mr_lawrence.mid"
)


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


# ---------------------------------------------------------------------------
# 簡單 3x5 字型，用於 INTRO "RHYTHM GAME" + 倒數數字（翻轉版）
# ---------------------------------------------------------------------------

FONT_3x5 = {
    "R": [
        "111",
        "101",
        "111",
        "110",
        "101",
    ],
    "H": [
        "101",
        "101",
        "111",
        "101",
        "101",
    ],
    "Y": [
        "101",
        "101",
        "111",
        "010",
        "010",
    ],
    "T": [
        "111",
        "010",
        "010",
        "010",
        "010",
    ],
    "M": [
        "101",
        "111",
        "111",
        "101",
        "101",
    ],
    "G": [
        "011",
        "100",
        "101",
        "101",
        "011",
    ],
    "A": [
        "010",
        "101",
        "111",
        "101",
        "101",
    ],
    "E": [
        "111",
        "100",
        "110",
        "100",
        "111",
    ],
    " ": [
        "000",
        "000",
        "000",
        "000",
        "000",
    ],
    "1": [
        "010",
        "110",
        "010",
        "010",
        "111",
    ],
    "2": [
        "111",
        "001",
        "111",
        "100",
        "111",
    ],
    "3": [
        "111",
        "001",
        "111",
        "001",
        "111",
    ],
    "4": [
        "101",
        "101",
        "111",
        "001",
        "001",
    ],
    "5": [
        "111",
        "100",
        "111",
        "001",
        "111",
    ],
}


# ---------------------------------------------------------------------------
# RhythmMode 本體
# ---------------------------------------------------------------------------

class RhythmMode:
    """
    Rhythm game mode.

    - 用同一首 MIDI 檔當「主旋律」來源。
    - 從 MIDI 解析所有 note，依時間做 clustering，只留下每一拍的「最高音」當作主旋律。
    - 每次只出現一顆 note（LED 只亮一個 key），按對時機得分。
    - 遊戲流程：
        1) INTRO：顯示 RHYTHM GAME + 5,4,3,2,1 倒數（字體做 180 度翻轉）
        2) PLAY：跟著主旋律出 note，可以按 button hit
        3) DONE：歌曲結束，顯示總分
    """

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

        # Time function（和 main 用同一種 monotonic）
        self._time_fn = time.monotonic

        # 遊戲階段：INTRO / PLAY / DONE
        self.phase: str = "INTRO"
        self.intro_start: float | None = None
        self.play_start: float | None = None  # 真正開始對齊 MIDI 的時間

        # INTRO 參數
        self.intro_total = 4.0  # 前 4 秒：顯示字 + 倒數
        self.countdown_start = 1.5  # 1.5 秒後開始 5→1 倒數

        # Chart notes
        self.chart_notes: List[ChartNote] = []
        self._notes_built: bool = False
        self.current_index: int = 0         # 下一顆 note index
        self.active_note: Optional[ChartNote] = None  # 正在被判定的那顆

        # 判定窗口（秒）
        self.perfect_window = 0.08   # |Δt| <= 80ms → 2 分
        self.good_window = 0.16      # |Δt| <= 160ms → 1 分
        self.miss_late_window = 0.25 # 超過這個就當 miss

        # 分數
        self.score: int = 0
        self.total_notes: int = 0
        self.max_score: int = 0

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

        self.total_notes = len(self.chart_notes)
        self.max_score = self.total_notes * 2

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
            print(f"[Rhythm] Failed to load MIDI: {self.midi_path} ({e})")
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
                    # 結束上一 cluster → 留最高音
                    best = max(cluster, key=lambda n: n.midi_note)
                    melody.append(best)
                    cluster = [note]

            # 最後一包
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
        專門給 rhythm mode 畫文字用的 helper：
        把 y 軸翻轉（0 在邏輯最上方 → 實際最下方）。

        不會影響 piano mode 的座標。
        """
        h = self.led.height
        # y=0 表示「邏輯上的最上面」，實際要畫在 h-1
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

        # 0.0 ~ 1.5 秒：顯示 "RHYTHM" / "GAME"
        if t < self.countdown_start:
            self._draw_text_center_flipped("RHYTHM", 2, (0, 180, 255))
            self._draw_text_center_flipped("GAME", 8, (255, 120, 0))

        # 1.5 秒之後：開始 5→1 倒數
        else:
            remain = max(0.0, self.intro_total - t)
            # 簡單切 5,4,3,2,1 每 0.5 秒
            step = int(remain / 0.5) + 1  # 1..8 大概，但是只用 5..1
            digit = min(5, max(1, step))

            self._draw_text_center_flipped("RHYTHM", 1, (0, 180, 255))
            self._draw_text_center_flipped("GAME", 7, (255, 120, 0))
            self._draw_text_center_flipped(str(digit), 4, (255, 255, 255))

        self.led.show()

        # 時間到 → 進 PLAY phase
        if t >= self.intro_total:
            self.phase = "PLAY"
            self.play_start = now
            self.current_index = 0
            self.active_note = None
            if self.debug:
                print("[Rhythm] INTRO finished. Start PLAY phase.")

    # ------------------------------------------------------------------
    # Hit 判定 & 分數
    # ------------------------------------------------------------------
    def _register_hit(self, note: ChartNote, dt: float) -> None:
        """
        dt: hit_time - note_time（秒）
        """
        if note.judged:
            return

        note.judged = True

        adt = abs(dt)
        if adt <= self.perfect_window:
            note.score = 2
        elif adt <= self.good_window:
            note.score = 1
        else:
            note.score = 0

        if note.score > 0:
            self.score += note.score

            # 播 hit 小音效
            if self.audio is not None:
                self.audio.play_hit_sfx()

        if self.debug:
            print(
                f"[Rhythm] HIT key={note.key} dt={dt:+.3f}s score={note.score} total={self.score}"
            )

    def _register_miss(self, note: ChartNote) -> None:
        if note.judged:
            return
        note.judged = True
        note.score = 0
        if self.debug:
            print(f"[Rhythm] MISS key={note.key}")

    # ------------------------------------------------------------------
    # handle_events: 只吃 NOTE_ON（button 按下）
    # ------------------------------------------------------------------
    def handle_events(self, events: List[InputEvent]) -> None:
        if self.phase != "PLAY":
            # 在 INTRO / DONE 狀態，按 button 不做判定
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

            # 只在有 active_note 時判定
            if self.active_note is None:
                continue

            note = self.active_note
            # 只允許對應的 key 才能 hit
            if ev.key != note.key:
                continue

            # note 的目標時間（相對 play_start）
            dt = song_time - note.time
            self._register_hit(note, dt)

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

        # 1) 控制 active_note 的生命週期
        self._update_active_note(song_time)

        # 2) 如果沒有 active_note，就看下一顆 note 要不要出現
        self._spawn_next_note_if_needed(song_time)

        # 3) 畫目前的狀態（只亮 active_note 的 key）
        self._render_play(song_time)

        # 4) 如果所有 note 都判定完，就進 DONE
        if self.current_index >= len(self.chart_notes) and self.active_note is None:
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
        if note.judged:
            # 已經 hit 或 miss → 可以關掉聲音、清掉 active
            if self.audio is not None:
                self.audio.note_off_midi(note.midi_note)
            self.active_note = None
            return

        # 看看是不是已經晚太多 → MISS
        dt = song_time - note.time
        if dt > self.miss_late_window:
            self._register_miss(note)
            if self.audio is not None:
                self.audio.note_off_midi(note.midi_note)
            self.active_note = None

    def _spawn_next_note_if_needed(self, song_time: float) -> None:
        # 如果還有 note，且目前沒有 active_note，就檢查下一顆要不要出現
        if self.active_note is not None:
            return
        if self.current_index >= len(self.chart_notes):
            return

        note = self.chart_notes[self.current_index]

        # 簡單的作法：當 song_time >= note.time - appear_lead，就讓它出現
        appear_lead = 0.15  # 提前 150ms 讓 key 亮起
        if song_time >= note.time - appear_lead:
            self.active_note = note
            self.current_index += 1

            # 播主旋律音
            if self.audio is not None:
                vel = int(max(0.1, min(1.0, note.velocity)) * 127)
                self.audio.note_on_midi(note.midi_note, vel)

            if self.debug:
                print(
                    f"[Rhythm] SPAWN note key={note.key} t={note.time:.3f} "
                    f"song_t={song_time:.3f}"
                )

    def _render_play(self, song_time: float) -> None:
        self.led.clear_all()

        # 畫 active note 的 key
        if self.active_note is not None:
            note = self.active_note
            # 根據時間差調整亮度：越接近目標時間越亮
            dt = song_time - note.time
            adt = abs(dt)
            # 簡單 Gaussian-ish 效果
            sigma = 0.12
            brightness = math.exp(-(adt ** 2) / (2 * sigma * sigma))
            brightness = max(0.2, min(1.0, brightness + 0.1))

            base_color = (0, 120, 255)
            r = int(base_color[0] * brightness)
            g = int(base_color[1] * brightness)
            b = int(base_color[2] * brightness)
            self.led.fill_key(note.key, (r, g, b), brightness=1.0)

        self.led.show()

    # ------------------------------------------------------------------
    # DONE 畫面：顯示分數（簡單版）
    # ------------------------------------------------------------------
    def _render_result(self, now: float) -> None:
        self.led.clear_all()

        # 用簡單方式在下方畫「Score 比例條」
        if self.max_score > 0:
            ratio = self.score / float(self.max_score)
        else:
            ratio = 0.0

        # 進度條長度 0..32
        bar_len = int(self.led.width * ratio + 0.5)
        for x in range(bar_len):
            for y in range(0, 3):
                self.led.set_xy(x, y, (0, 255, 0))

        # 上面顯示 "END"
        self._draw_text_center_flipped("END", 9, (255, 255, 255))

        self.led.show()
