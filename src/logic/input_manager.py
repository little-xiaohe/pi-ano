# src/logic/input_manager.py

from typing import List

from src.logic.input_event import InputEvent, EventType
from src.logic.modes.menu_mode import MenuMode
from src.logic.modes.piano_mode import PianoMode
from src.logic.modes.rhythm_mode import RhythmMode
from src.logic.modes.midi_song_mode import MidiSongMode
from src.hardware.pico.pico_mode_display import PicoModeDisplay


class InputManager:
    def __init__(
        self,
        menu,
        piano,
        rhythm,
        song,
        pico_display: PicoModeDisplay | None = None,   # ★ 新增
    ):
        self.menu = menu
        self.piano = piano
        self.rhythm = rhythm
        self.song = song

        self.pico_display = pico_display               # ★ 新增

        self.current_mode = "menu"
        self._mode_order = ["menu", "piano", "rhythm", "song"]

    # --------------------- Event handling ---------------------

    def handle_events(self, events: List[InputEvent], now: float) -> None:
        # 1) 先處理「mode 類型」事件（全域）
        for ev in events:
            # ---- MODE_SWITCH: keyboard 指令 ----
            if ev.type == EventType.MODE_SWITCH and ev.mode_name in (
                "menu",
                "piano",
                "rhythm",
                "song",
            ):
                self._switch_mode(ev.mode_name, now)

            # ---- NEXT_SONG: keyboard "next" ----
            elif ev.type == EventType.NEXT_SONG:
                if self.current_mode == "song":
                    print("[IM] NEXT_SONG: already in song mode → skip_to_next()")
                    self.song.skip_to_next(now)
                else:
                    print("[IM] NEXT_SONG: switch to song mode")
                    self._switch_mode("song", now)

            # ---- NEXT_MODE: button 長按 D14 ----
            elif ev.type == EventType.NEXT_MODE:
                self._cycle_mode(now)

        # 2) 把 NOTE 類事件丟給目前 active 的 mode
        note_events = [
            e for e in events if e.type in (EventType.NOTE_ON, EventType.NOTE_OFF)
        ]
        if not note_events:
            return

        if self.current_mode == "piano":
            self.piano.handle_events(note_events)
        elif self.current_mode == "rhythm":
            self.rhythm.handle_events(note_events)
        elif self.current_mode == "song":
            # song mode 目前不吃外部 NOTE（全部來自 MIDI）
            pass
        else:
            # menu mode：暫時忽略 NOTE（如有彩蛋可在這裡加）
            pass

    def _switch_mode(self, mode_name: str, now: float) -> None:
        if mode_name == self.current_mode:
            return

        old_mode = self.current_mode

        # --- on-exit hooks for old mode ---
        if old_mode == "rhythm":
            self.rhythm.on_exit()
        # 如果之後 song 有 scheduler，也可以做 self.song.on_exit()

        # --- switch current mode ---
        self.current_mode = mode_name
        print(f"[MODE] Switched to: {self.current_mode.upper()}")

        # --- per-mode on-enter behavior ---
        if mode_name == "menu":
            self.menu.reset(now)
        elif mode_name == "piano":
            if hasattr(self.piano, "randomize_palette"):
                self.piano.randomize_palette()
        elif mode_name == "rhythm":
            self.rhythm.reset(now)
        elif mode_name == "song":
            self.song.reset(now)

        # --- notify Pico ---
        if self.pico_display is not None:
            self.pico_display.show_mode(mode_name)


    def _cycle_mode(self, now: float) -> None:
        """長按 D14 時呼叫：依序輪到下一個 mode。"""
        try:
            idx = self._mode_order.index(self.current_mode)
        except ValueError:
            # 不在列表裡的話，直接回到 menu
            next_mode = "menu"
        else:
            next_mode = self._mode_order[(idx + 1) % len(self._mode_order)]

        print(f"[MODE] NEXT_MODE → {next_mode.upper()}")
        self._switch_mode(next_mode, now)

    # --------------------- Update active mode ---------------------

    def update(self, now: float) -> None:
        if self.current_mode == "piano":
            self.piano.update(now)
        elif self.current_mode == "rhythm":
            self.rhythm.update(now)
        elif self.current_mode == "song":
            self.song.update(now)
        else:
            self.menu.update(now)
