from __future__ import annotations

from typing import List, Optional

from src.logic.input_event import InputEvent, EventType
from src.hardware.config.keys import KeyId
from src.hardware.pico.pico_mode_display import PicoModeDisplay
from src.logic.high_scores import HighScoreStore  # 儲存 rhythm 各難度最高分


class InputManager:
    """
    Central router for all input events (keyboard, buttons, IR) and
    for high-level mode transitions.

    Modes:
        - "menu"   → MenuMode
        - "piano"  → PianoMode
        - "rhythm" → RhythmMode
        - "song"   → MidiSongMode
    """

    def __init__(
        self,
        menu,
        piano,
        rhythm,
        song,
        pico_display: Optional[PicoModeDisplay] = None,
    ) -> None:
        self.menu = menu
        self.piano = piano
        self.rhythm = rhythm
        self.song = song

        self.pico_display = pico_display

        self.current_mode: str = "menu"
        self._mode_order = ["menu", "piano", "rhythm", "song"]

        # Rhythm high scores and post-game timeline state
        self._high_scores = HighScoreStore()
        self._rhythm_postgame_started: bool = False
        self._rhythm_postgame_stage: Optional[str] = None
        # stages: "result_scroll" → "user_label" → "user_score" → "best_label" → "best_score"
        self._rhythm_postgame_t0: float = 0.0
        self._rhythm_last_score: int = 0
        self._rhythm_last_best: int = 0
        self._rhythm_last_max_score: int = 0
        self._rhythm_last_difficulty: str = "easy"

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def current_mode_name(self) -> str:
        return self.current_mode

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_audio_engine(self):
        """
        Try to get the shared AudioEngine from one of piano / rhythm / song.
        """
        for mode in (self.piano, self.rhythm, self.song):
            audio = getattr(mode, "audio", None)
            if audio is not None:
                return audio
        return None

    # ------------------------------------------------------------------
    # Mode switching helpers
    # ------------------------------------------------------------------

    def _cycle_mode(self, now: float) -> None:
        if self.current_mode not in self._mode_order:
            next_mode = "menu"
        else:
            idx = self._mode_order.index(self.current_mode)
            next_mode = self._mode_order[(idx + 1) % len(self._mode_order)]
        self._switch_mode(next_mode, now)

    def _switch_mode(self, mode_name: str, now: float) -> None:
        if mode_name == self.current_mode:
            return

        # Exit old mode
        if self.current_mode == "rhythm":
            if hasattr(self.rhythm, "on_exit"):
                self.rhythm.on_exit()
            self._rhythm_postgame_started = False
            self._rhythm_postgame_stage = None

        self.current_mode = mode_name
        print(f"[MODE] Switched to: {self.current_mode.upper()}")

        # Enter new mode
        if mode_name == "menu":
            if hasattr(self.menu, "reset"):
                self.menu.reset(now)

        elif mode_name == "piano":
            if hasattr(self.piano, "randomize_palette"):
                self.piano.randomize_palette()
            if hasattr(self.piano, "reset"):
                self.piano.reset(now)

        elif mode_name == "rhythm":
            self._rhythm_postgame_started = False
            self._rhythm_postgame_stage = None
            # Pico 端會在 MODE:rhythm 時自行做：RYTHM.bmp(3s) → attract loop
            self.rhythm.reset(now)

        elif mode_name == "song":
            self.song.reset(now)

        # Notify Pico to switch mode (MODE:<name>)
        if self.pico_display is not None:
            try:
                self.pico_display.show_mode(mode_name)
            except Exception as e:
                print("[InputManager] pico_display.show_mode error:", e)

    # ------------------------------------------------------------------
    # Pico messages (Pico → Pi)
    # ------------------------------------------------------------------

    def _handle_pico_message(self, msg: str, now: float) -> None:
        if not msg:
            return
        text = msg.strip()
        if not text:
            return

        up = text.upper()

        if up.startswith("RHYTHM:COUNTDOWN_DONE"):
            if self.current_mode == "rhythm":
                print("[InputManager] Pico → RHYTHM:COUNTDOWN_DONE")
                try:
                    self.rhythm.start_play_after_countdown(now)
                except Exception as e:
                    print("[InputManager] rhythm.start_play_after_countdown error:", e)

                # IMPORTANT:
                # Do NOT send RHYTHM:LEVEL here.
                # In the new Pico code.py, RHYTHM:LEVEL triggers countdown.
                # Sending it again would restart countdown or mess up state.

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_events(self, events: List[InputEvent], now: float) -> None:
        # 1) Global events: mode switch / next mode / song-mode specific "next song" / NEXT_SF2
        for ev in events:
            # Long press KEY_0: switch SoundFont
            if ev.type == EventType.NEXT_SF2:
                audio = self._get_audio_engine()
                if audio is not None:
                    try:
                        audio.cycle_soundfont()
                    except Exception as e:
                        print("[InputManager] audio.cycle_soundfont error:", e)
                continue

            if ev.type == EventType.MODE_SWITCH and ev.mode_name:
                self._switch_mode(ev.mode_name, now)
                continue

            if ev.type == EventType.NEXT_MODE:
                self._cycle_mode(now)
                continue

            # SONG mode: press KEY_3 (button) → next song (by playlist order)
            if (
                self.current_mode == "song"
                and ev.type == EventType.NOTE_ON
                and ev.key == KeyId.KEY_3
                and getattr(ev, "source", None) == "button"
            ):
                try:
                    self.song.skip_to_next(now)
                except Exception as e:
                    print("[InputManager] song.skip_to_next error:", e)
                continue

            # Do not handle EventType.NEXT_SONG here, leave for MidiSongMode.handle_events()
            # (e.g., keyboard input 'next')

        # 2) Mode-specific event handling
        if self.current_mode == "menu":
            if hasattr(self.menu, "handle_events"):
                self.menu.handle_events(events)

        elif self.current_mode == "piano":
            filtered: List[InputEvent] = []
            for ev in events:
                if ev.type in (EventType.NOTE_ON, EventType.NOTE_OFF):
                    if getattr(ev, "source", None) == "button":
                        # In piano mode, do not use button to play notes, only for mode switch / NEXT_SF2
                        continue
                filtered.append(ev)
            if hasattr(self.piano, "handle_events"):
                self.piano.handle_events(filtered)

        elif self.current_mode == "rhythm":
            self._handle_rhythm_events(events, now)

        elif self.current_mode == "song":
            if hasattr(self.song, "handle_events"):
                # Pass other events (e.g., keyboard 'next' → NEXT_SONG) to MidiSongMode
                self.song.handle_events(events)

    # ------------------------------------------------------------------
    # Rhythm-specific events
    # ------------------------------------------------------------------

    def _handle_rhythm_events(self, events: List[InputEvent], now: float) -> None:
        phase = getattr(self.rhythm, "phase", None)

        # WAIT_COUNTDOWN: select difficulty
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

                try:
                    self.rhythm.set_difficulty(difficulty)
                except Exception as e:
                    print(f"[InputManager] rhythm.set_difficulty('{difficulty}') error:", e)

                print(f"[InputManager] Rhythm difficulty selected: {difficulty}")

                # NEW FLOW:
                # Send RHYTHM:LEVEL:<diff> to Pico.
                # Pico will immediately start countdown and later print RHYTHM:COUNTDOWN_DONE.
                # Do NOT send RHYTHM:COUNTDOWN anymore.
                if self.pico_display is not None:
                    try:
                        self.pico_display.send_rhythm_level(difficulty)
                    except Exception as e:
                        print("[InputManager] pico_display.send_rhythm_level error:", e)

                return

            return

        # PLAY: treat button press as hit
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

        # DONE / others: do not handle events
        return

    # ------------------------------------------------------------------
    # Rhythm post-game timeline (Pi controls the entire rhythm post-game sequence)
    # ------------------------------------------------------------------

    def _maybe_run_rhythm_postgame_timeline(self, now: float) -> None:
        """
        After phase == DONE:

            First time seeing DONE:
                - Read score / max_score / difficulty
                - Update high score
                - Send CHALLENGE_FAIL or CHALLENGE_SUCCESS (first marquee)
                - stage = "result_scroll"

            Timeline:
                "result_scroll" 5.5s  → send USER_SCORE_LABEL   (YOUR SCORE marquee)
                "user_label"    4.0s  → send USER_SCORE        (show x/y)
                "user_score"    3.0s  → send BEST_SCORE_LABEL  (BEST SCORE marquee)
                "best_label"    4.0s  → send BEST_SCORE        (show best/y)
                "best_score"    3.0s  → send BACK_TO_TITLE and reset rhythm()
        """
        phase = getattr(self.rhythm, "phase", None)

        if phase != "DONE":
            self._rhythm_postgame_started = False
            self._rhythm_postgame_stage = None
            return

        if self.pico_display is None:
            return

        # ---- First time seeing DONE: initialize ----
        if not self._rhythm_postgame_started:
            self._rhythm_postgame_started = True
            self._rhythm_postgame_stage = "result_scroll"
            self._rhythm_postgame_t0 = now

            score = getattr(self.rhythm, "score", 0)
            max_score = getattr(self.rhythm, "max_score", 0)
            difficulty = getattr(self.rhythm, "difficulty", "easy")

            self._rhythm_last_score = score
            self._rhythm_last_max_score = max_score
            self._rhythm_last_difficulty = difficulty

            best_before = self._high_scores.get_best(difficulty)
            is_new_record = self._high_scores.update_if_better(difficulty, score)
            best_after = max(best_before, score)
            self._rhythm_last_best = best_after

            print(
                f"[InputManager] Rhythm DONE: {score}/{max_score}, "
                f"best={best_before}→{best_after}, diff={difficulty}, "
                f"new_record={is_new_record}"
            )

            try:
                if is_new_record:
                    self.pico_display.send_rhythm_challenge_success()
                else:
                    self.pico_display.send_rhythm_challenge_fail()
            except Exception as e:
                print("[InputManager] pico_display.send_rhythm_challenge_* error:", e)

            return

        # ---- Afterward, control by stage + elapsed ----
        stage = self._rhythm_postgame_stage
        elapsed = now - self._rhythm_postgame_t0

        # 1) FAIL / NEW RECORD! marquee
        if stage == "result_scroll":
            if elapsed >= 4.0:
                try:
                    self.pico_display.send_rhythm_user_score_label()
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_user_score_label error:", e)
                self._rhythm_postgame_stage = "user_label"
                self._rhythm_postgame_t0 = now

        # 2) YOUR SCORE marquee
        elif stage == "user_label":
            if elapsed >= 3.0:
                score = self._rhythm_last_score
                max_score = self._rhythm_last_max_score
                if max_score > 0:
                    user_text = f"{score}/{max_score}"
                else:
                    user_text = str(score)
                try:
                    self.pico_display.send_rhythm_user_score(user_text)
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_user_score error:", e)
                self._rhythm_postgame_stage = "user_score"
                self._rhythm_postgame_t0 = now

        # 3) Show user score static
        elif stage == "user_score":
            if elapsed >= 3.0:
                try:
                    self.pico_display.send_rhythm_best_score_label()
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_best_score_label error:", e)
                self._rhythm_postgame_stage = "best_label"
                self._rhythm_postgame_t0 = now

        # 4) BEST SCORE marquee
        elif stage == "best_label":
            if elapsed >= 3.0:
                best = self._rhythm_last_best
                max_score = self._rhythm_last_max_score
                if max_score > 0:
                    best_text = f"{best}/{max_score}"
                else:
                    best_text = str(best)
                try:
                    self.pico_display.send_rhythm_best_score(best_text)
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_best_score error:", e)
                self._rhythm_postgame_stage = "best_score"
                self._rhythm_postgame_t0 = now

        # 5) Show best score static → back to title + reset
        elif stage == "best_score":
            if elapsed >= 3.0:
                try:
                    self.pico_display.send_rhythm_back_to_title()
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_back_to_title error:", e)

                try:
                    self.rhythm.reset(now)
                except Exception as e:
                    print("[InputManager] rhythm.reset error after post-game:", e)

                self._rhythm_postgame_started = False
                self._rhythm_postgame_stage = None

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, now: float) -> None:
        # 1) Poll Pico messages every frame
        if self.pico_display is not None:
            try:
                messages = self.pico_display.poll_messages()
            except Exception as e:
                print("[InputManager] pico_display.poll_messages error:", e)
                messages = []

            for msg in messages:
                self._handle_pico_message(msg, now)

        # 2) Normal mode updates
        if self.current_mode == "menu":
            if hasattr(self.menu, "update"):
                self.menu.update(now)

        elif self.current_mode == "piano":
            if hasattr(self.piano, "update"):
                self.piano.update(now)

        elif self.current_mode == "rhythm":
            if hasattr(self.rhythm, "update"):
                self.rhythm.update(now)
            # Rhythm post-game sequence
            self._maybe_run_rhythm_postgame_timeline(now)

        elif self.current_mode == "song":
            if hasattr(self.song, "update"):
                self.song.update(now)
