# src/logic/input_manager.py

from typing import List

from src.logic.input_event import InputEvent, EventType
from src.logic.modes.chiikawa_mode import ChiikawaMode
from src.logic.modes.piano_mode import PianoMode
from src.logic.modes.rhythm_mode import RhythmMode
from src.logic.modes.midi_song_mode import MidiSongMode


class InputManager:
    """
    Central mode/state manager.

    Modes:
      - "chiikawa" : menu / home screen
      - "piano"    : piano playing mode
      - "rhythm"   : rhythm game mode
      - "song"     : MIDI playlist mode

    Responsibilities:
      - Track current_mode.
      - Handle MODE_SWITCH and NEXT_SONG (不分現在在哪個 mode).
      - Forward NOTE_ON / NOTE_OFF to the active mode.
      - Call update(now) on the active mode every frame.
    """

    def __init__(
        self,
        chiikawa: ChiikawaMode,
        piano: PianoMode,
        rhythm: RhythmMode,
        song: MidiSongMode,
    ) -> None:
        self.chiikawa = chiikawa
        self.piano = piano
        self.rhythm = rhythm
        self.song = song

        # 一開始你想要在哪個 mode
        self.current_mode: str = "chiikawa"

    # --------------------- Event handling ---------------------

    def handle_events(self, events: List[InputEvent], now: float) -> None:
        # 1) 先處理「mode 類型」事件
        #    （這些是全域的，跟 current_mode 無關）
        for ev in events:
            # ---- MODE_SWITCH: 切換 mode ----
            if ev.type == EventType.MODE_SWITCH and ev.mode_name in (
                "chiikawa",
                "piano",
                "rhythm",
                "song",
            ):
                self._switch_mode(ev.mode_name, now)

            # ---- NEXT_SONG: 根據 current_mode 決定行為 ----
            elif ev.type == EventType.NEXT_SONG:
                if self.current_mode == "song":
                    # 已在 song mode → 下一首
                    print("[IM] NEXT_SONG: already in song mode → skip_to_next()")
                    self.song.skip_to_next(now)
                else:
                    # 不在 song mode → 先切到 song
                    print("[IM] NEXT_SONG: switch to song mode")
                    self._switch_mode("song", now)

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
            # chiikawa 預設忽略 NOTE（或你之後想讓它做彩蛋也可以在這邊加）
            self.chiikawa.handle_events(note_events)

    # --------------------- Mode switching ---------------------

    def _switch_mode(self, mode_name: str, now: float) -> None:
        if mode_name == self.current_mode:
            return

        self.current_mode = mode_name
        print(f"[MODE] Switched to: {self.current_mode.upper()}")

        if mode_name == "chiikawa":
            self.chiikawa.reset(now)

        elif mode_name == "piano":
            # 進入 piano mode：如果你有 random palette 可以在這裡換
            if hasattr(self.piano, "randomize_palette"):
                self.piano.randomize_palette()

        elif mode_name == "rhythm":
            self.rhythm.reset(now)

        elif mode_name == "song":
            self.song.reset(now)

    # --------------------- Update active mode ---------------------

    def update(self, now: float) -> None:
        if self.current_mode == "piano":
            self.piano.update(now)
        elif self.current_mode == "rhythm":
            self.rhythm.update(now)
        elif self.current_mode == "song":
            self.song.update(now)
        else:
            self.chiikawa.update(now)
