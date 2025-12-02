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

    - 有自己的 scheduler（用 next_on_index / next_off_index）
    - 支援「歌單」：進入 song mode 時，從 midi_folder 隨機挑一首
    - 一首播完後可以選擇是否自動換下一首
    """

    def __init__(
        self,
        led: LedMatrix,
        audio: Optional[AudioEngine],
        midi_folder: str = "/home/pi/pi-ano/src/hardware/audio/assets/midi",
        loop_playlist: bool = True,   # True: 一首播完自動換下一首
        debug: bool = False,
    ) -> None:
        self.led = led
        self.audio = audio
        self.debug = debug
        self.loop_playlist = loop_playlist

        self.start_time: Optional[float] = None

        # --- 準備歌單 ---
        folder = Path(midi_folder)
        self.playlist: List[Path] = sorted(
            [p for p in folder.glob("*.mid*") if p.is_file()]
        )
        if not self.playlist:
            raise FileNotFoundError(f"No MIDI files found in folder: {folder}")

        # 現在正在播的這一首歌
        self.current_song: Optional[Path] = None

        # 這首歌的所有 note events（global time）
        self.events: List[MidiNoteEvent] = []

        # scheduler 指標
        self.next_on_index: int = 0
        self.next_off_index: int = 0

        # 正在亮的 LED notes
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
            current_time += msg.time

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

        # 萬一有 note 沒收到 note_off，就給一個 fallback 長度
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

    # MIDI note → 5 個 LED key（mod 5）
    def _midi_note_to_key(self, midi_note: int) -> KeyId:
        """
        用 modulo-5 把 MIDI 音高丟到 5 個 key：

        - 先用 C4 = 60 當作基準
        - (midi_note - base) % 5 給你 0..4
        - 對應到 KEY_0..KEY_4
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
        """選一首新歌、載入、重置 scheduler，並換一組顏色。"""
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

        if self.debug:
            print(f"[MidiSongMode] Start playing: {self.current_song.name} at t={now:.3f}")
            print(f"[MidiSongMode] Palette changed for this song")

    def reset(self, now: float) -> None:
        """
        每次進入 song mode 或想重播歌單時呼叫。

        這裡的策略是：
        - 每次 reset 都隨機挑一首歌重新開始。
        """
        self._start_new_song(now)

    def handle_events(self, events: List[object]) -> None:
        """
        目前先忽略外部輸入。

        之後如果你想在 song mode 裡加 "skip" / "back" / "stop" 指令，
        可以在這裡處理 keyboard 的 InputEvent。
        """
        return

    # ------------------------------------------------------------------
    # Main update（scheduler）
    # ------------------------------------------------------------------
    def update(self, now: float) -> None:
        if self.start_time is None:
            # 第一次 update → 隨機挑一首歌
            self._start_new_song(now)

        t = now - self.start_time
        eps = 0.002  # 小容忍誤差

        # 1) 觸發 NOTE_ON（只看還沒播過的 notes）
        while self.next_on_index < len(self.events):
            ev = self.events[self.next_on_index]
            if ev.start_time <= t + eps:
                self._trigger_note_on(ev, t)
                self.next_on_index += 1
            else:
                break

        # 2) 觸發 NOTE_OFF
        while self.next_off_index < len(self.events):
            ev = self.events[self.next_off_index]
            if ev.end_time <= t + eps:
                self._trigger_note_off(ev, t)
                self.next_off_index += 1
            else:
                break

        # 3) 更新 LED 畫面
        self._update_leds(t)

        # 4) 這首歌播完了嗎？
        if self.next_off_index >= len(self.events) and not self.active_led_notes:
            if self.loop_playlist:
                # 自動換下一首
                self._start_new_song(now)
            else:
                # 不 loop：播完就靜音（保留在最後一幀）
                pass

    # ------------------------------------------------------------------
    # Helpers: 音 & LED
    # ------------------------------------------------------------------
    def _trigger_note_on(self, ev: MidiNoteEvent, t: float) -> None:
        """在時間 t 觸發一個 NOTE_ON（聲音 + 加到 active_led_notes）"""
        key = self._midi_note_to_key(ev.midi_note)

        # LED
        self.active_led_notes[key] = ActiveLedNote(
            key=key,
            velocity=ev.velocity,
            end_time=ev.end_time,
        )

        # 音
        if self.audio is not None:
            try:
                vel127 = max(1, min(127, int(ev.velocity * 127)))
                self.audio.fs.noteon(self.audio.channel, ev.midi_note, vel127)
            except Exception as e:
                if self.debug:
                    print("[MidiSongMode] audio noteon error:", e)

        if self.debug:
            song = self.current_song.name if self.current_song else "?"
            print(
                f"[MidiSongMode] NOTE_ON t={t:.3f}s song={song} "
                f"midi={ev.midi_note} -> key={int(key)}, vel={ev.velocity:.2f}"
            )

    def _trigger_note_off(self, ev: MidiNoteEvent, t: float) -> None:
        """在時間 t 觸發 NOTE_OFF（聲音關掉，LED 由 _update_leds 控制）"""
        if self.audio is not None:
            try:
                self.audio.fs.noteoff(self.audio.channel, ev.midi_note)
            except Exception as e:
                if self.debug:
                    print("[MidiSongMode] audio noteoff error:", e)

        if self.debug:
            print(
                f"[MidiSongMode] NOTE_OFF t={t:.3f}s midi={ev.midi_note}"
            )

    def _update_leds(self, t: float) -> None:
        """依照 active_led_notes 把 LED 畫出來，過期的 note 自動移除。"""
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
        # 關掉目前所有音符（避免殘音）
        if self.audio is not None:
            try:
                for note in range(128):
                    self.audio.fs.noteoff(self.audio.channel, note)
            except Exception as e:
                if self.debug:
                    print("[MidiSongMode] skip_to_next noteoff error:", e)

        # 清掉 LED 畫面
        self.led.clear_all()
        self.led.show()

        # 開下一首
        self._start_new_song(now)

        if self.debug:
            print("[MidiSongMode] Skipped to next song")
