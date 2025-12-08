# src/logic/input_manager.py

from __future__ import annotations

from typing import List, Optional

from src.logic.input_event import InputEvent, EventType
from src.hardware.config.keys import KeyId
from src.hardware.pico.pico_mode_display import PicoModeDisplay


class InputManager:
    """
    Central router for all input events (keyboard, buttons, IR) and
    for high-level mode transitions.

    Modes:
      - "menu"   → MenuMode
      - "piano"  → PianoMode
      - "rhythm" → RhythmMode  (rhythm game with easy/medium/hard)
      - "song"   → MidiSongMode

    Responsibilities:
      - Handle MODE_SWITCH / NEXT_MODE (long press D14) / NEXT_SONG.
      - Route NOTE_ON / NOTE_OFF to the correct mode.
      - Piano mode:
          * Buttons only used for NEXT_MODE, not for playing notes.
      - Rhythm mode:
          * phase == "WAIT_COUNTDOWN":
              - D15 (KEY_3) → easy
              - D18 (KEY_2) → medium
              - D24 (KEY_1) → hard
              - After selecting difficulty, ask Pico to start countdown.
          * When Pico prints "RHYTHM:COUNTDOWN_DONE":
              - rhythm.start_play_after_countdown(now)
              - PicoModeDisplay.send_rhythm_level(difficulty)
          * When rhythm.phase becomes "DONE":
              - send RHYTHM:RESULT:x/y to Pico once.
    """

    def __init__(
        self,
        menu,
        piano,
        rhythm,
        song,
        pico_display: Optional[PicoModeDisplay] = None,
    ) -> None:
        # Mode instances
        self.menu = menu
        self.piano = piano
        self.rhythm = rhythm
        self.song = song

        # External Pico LED driver (can be None)
        self.pico_display = pico_display

        # Current mode name
        self.current_mode: str = "menu"

        # Mode order for NEXT_MODE cycling (long press KEY_4)
        self._mode_order = ["menu", "piano", "rhythm", "song"]

        # Rhythm result → send to Pico only once
        self._rhythm_result_sent: bool = False

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def current_mode_name(self) -> str:
        return self.current_mode

    # ------------------------------------------------------------------
    # Mode switching helpers
    # ------------------------------------------------------------------

    def _cycle_mode(self, now: float) -> None:
        """
        Long-press on KEY_4 (D14) → cycle to next mode in self._mode_order.
        """
        if self.current_mode not in self._mode_order:
            next_mode = "menu"
        else:
            idx = self._mode_order.index(self.current_mode)
            next_mode = self._mode_order[(idx + 1) % len(self._mode_order)]

        self._switch_mode(next_mode, now)

    def _switch_mode(self, mode_name: str, now: float) -> None:
        """
        Core mode switch routine.

        - Stops rhythm audio when leaving rhythm mode.
        - Calls reset(...) on modes that need fresh state.
        - Notifies Pico about MODE:xxx (if pico_display available).
        """
        if mode_name == self.current_mode:
            return

        # --- leaving old mode: clean up if needed ---
        if self.current_mode == "rhythm":
            if hasattr(self.rhythm, "on_exit"):
                self.rhythm.on_exit()

        self.current_mode = mode_name
        print(f"[MODE] Switched to: {self.current_mode.upper()}")

        # --- entering new mode ---
        if mode_name == "menu":
            if hasattr(self.menu, "reset"):
                self.menu.reset(now)

        elif mode_name == "piano":
            if hasattr(self.piano, "randomize_palette"):
                self.piano.randomize_palette()
            if hasattr(self.piano, "reset"):
                self.piano.reset(now)

        elif mode_name == "rhythm":
            self._rhythm_result_sent = False
            self.rhythm.reset(now)

        elif mode_name == "song":
            self.song.reset(now)

        # --- notify Pico about the current mode (MODE:menu/piano/rhythm/song) ---
        if self.pico_display is not None:
            try:
                self.pico_display.show_mode(mode_name)
            except Exception as e:
                print("[InputManager] pico_display.show_mode error:", e)

    # ------------------------------------------------------------------
    # Pico messages (Pico → Pi)
    # ------------------------------------------------------------------

    def _handle_pico_message(self, msg: str, now: float) -> None:
        """
        Handle messages printed by Pico over USB serial.

        We only care about:
          RHYTHM:COUNTDOWN_DONE
        """
        if not msg:
            return

        text = msg.strip()
        if not text:
            return

        up = text.upper()

        # Countdown finished on Pico → start rhythm game on Pi.
        if up.startswith("RHYTHM:COUNTDOWN_DONE"):
            if self.current_mode == "rhythm":
                print("[InputManager] Pico → RHYTHM:COUNTDOWN_DONE")
                # Start actual game on rhythm side
                try:
                    self.rhythm.start_play_after_countdown(now)
                except Exception as e:
                    print("[InputManager] rhythm.start_play_after_countdown error:", e)

                # 告訴 Pico 目前的難度，讓它顯示 HARD / MEDIUM / EASY
                if self.pico_display is not None:
                    try:
                        difficulty = getattr(self.rhythm, "difficulty", "easy")
                        self.pico_display.send_rhythm_level(difficulty)
                    except Exception as e:
                        print("[InputManager] pico_display.send_rhythm_level error:", e)

    # ------------------------------------------------------------------
    # Event handling (Pi → modes)
    # ------------------------------------------------------------------

    def handle_events(self, events: List[InputEvent], now: float) -> None:
        """
        Handle all input events for this frame.

        Order:
          1) Global events (mode switch, next mode, next song)
          2) Mode-specific routing (menu / piano / rhythm / song)
        """
        # ---------------------
        # 1) Global events
        # ---------------------
        for ev in events:
            # Keyboard: "mode xxx"
            if ev.type == EventType.MODE_SWITCH and ev.mode_name:
                self._switch_mode(ev.mode_name, now)
                continue

            # Button long press on KEY_4 (D14) → NEXT_MODE
            if ev.type == EventType.NEXT_MODE:
                self._cycle_mode(now)
                continue

            # Keyboard: "next" (only meaningful in song mode)
            if ev.type == EventType.NEXT_SONG and self.current_mode == "song":
                try:
                    self.song.skip_to_next(now)
                except Exception as e:
                    print("[InputManager] song.skip_to_next error:", e)
                continue

        # ---------------------
        # 2) Mode-specific events
        # ---------------------
        if self.current_mode == "menu":
            if hasattr(self.menu, "handle_events"):
                self.menu.handle_events(events)

        elif self.current_mode == "piano":
            filtered: List[InputEvent] = []
            for ev in events:
                if ev.type in (EventType.NOTE_ON, EventType.NOTE_OFF):
                    if getattr(ev, "source", None) == "button":
                        continue
                filtered.append(ev)

            if hasattr(self.piano, "handle_events"):
                self.piano.handle_events(filtered)

        elif self.current_mode == "rhythm":
            self._handle_rhythm_events(events, now)

        elif self.current_mode == "song":
            if hasattr(self.song, "handle_events"):
                self.song.handle_events(events)

    # ------------------------------------------------------------------
    # Rhythm-specific event handling (difficulty + hits)
    # ------------------------------------------------------------------

    def _handle_rhythm_events(self, events: List[InputEvent], now: float) -> None:
        """
        Rhythm mode has two stages:
          - phase == "WAIT_COUNTDOWN":
              difficulty selection via buttons, then ask Pico to start countdown.
          - phase == "PLAY":
              button NOTE_ON events are rhythm hits.
        """
        phase = getattr(self.rhythm, "phase", None)

        # -----------------------------
        # Difficulty selection phase
        # -----------------------------
        if phase == "WAIT_COUNTDOWN":
            for ev in events:
                if ev.type != EventType.NOTE_ON:
                    continue
                if getattr(ev, "source", None) != "button":
                    continue
                if ev.key is None:
                    continue

                difficulty: Optional[str] = None
                if ev.key == KeyId.KEY_3:
                    difficulty = "easy"
                elif ev.key == KeyId.KEY_2:
                    difficulty = "medium"
                elif ev.key == KeyId.KEY_1:
                    difficulty = "hard"

                if difficulty is None:
                    continue

                # Set difficulty in RhythmMode
                try:
                    self.rhythm.set_difficulty(difficulty)
                except Exception as e:
                    print(f"[InputManager] rhythm.set_difficulty('{difficulty}') error:", e)

                print(f"[InputManager] Rhythm difficulty selected: {difficulty}")

                # Ask Pico to start 5→1 countdown
                if self.pico_display is not None:
                    try:
                        self.pico_display.send_rhythm_countdown()
                    except Exception as e:
                        print("[InputManager] pico_display.send_rhythm_countdown error:", e)

                # Only first valid press matters
                return

            # no difficulty button this frame
            return

        # -----------------------------
        # PLAY phase → handle hits
        # -----------------------------
        if phase == "PLAY":
            button_events: List[InputEvent] = [
                ev
                for ev in events
                if getattr(ev, "source", None) == "button"
                and ev.type in (EventType.NOTE_ON, EventType.NOTE_OFF)
            ]
            if button_events and hasattr(self.rhythm, "handle_events"):
                self.rhythm.handle_events(button_events)
            return

        # DONE / other phases → nothing
        return

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, now: float) -> None:
        """
        Per-frame update for the currently active mode, plus
        polling any messages from Pico.
        """
        # 1) Poll Pico messages (RHYTHM:COUNTDOWN_DONE, etc.)
        if self.pico_display is not None:
            try:
                messages = self.pico_display.poll_messages()
            except Exception as e:
                print("[InputManager] pico_display.poll_messages error:", e)
                messages = []

            for msg in messages:
                self._handle_pico_message(msg, now)

        # 2) Update active mode
        if self.current_mode == "menu":
            if hasattr(self.menu, "update"):
                self.menu.update(now)

        elif self.current_mode == "piano":
            if hasattr(self.piano, "update"):
                self.piano.update(now)

        elif self.current_mode == "rhythm":
            if hasattr(self.rhythm, "update"):
                self.rhythm.update(now)

            # Rhythm 結束 → 傳分數到 Pico（只傳一次）
            phase = getattr(self.rhythm, "phase", None)
            if phase == "DONE" and not self._rhythm_result_sent:
                self._rhythm_result_sent = True
                score = getattr(self.rhythm, "score", 0)
                max_score = getattr(self.rhythm, "max_score", 0)
                print(f"[InputManager] Rhythm result: {score}/{max_score}")

                if self.pico_display is not None:
                    try:
                        self.pico_display.send_rhythm_result(score, max_score)
                    except Exception as e:
                        print("[InputManager] pico_display.send_rhythm_result error:", e)

        elif self.current_mode == "song":
            if hasattr(self.song, "update"):
                self.song.update(now)
