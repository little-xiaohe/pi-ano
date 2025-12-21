# src/logic/input_manager.py

from __future__ import annotations

from typing import List, Optional

from src.logic.input_event import InputEvent, EventType
from src.hardware.config.keys import KeyId
from src.hardware.pico.pico_mode_display import PicoModeDisplay
from src.logic.high_scores import HighScoreStore


class InputManager:
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
        # stages:
        #   "result_scroll" → "user_label" → "user_score" → "best_label"
        #   → "best_score_wait_done" → "pi_mode_colors_hold"
        self._rhythm_postgame_t0: float = 0.0
        self._rhythm_last_score: int = 0
        self._rhythm_last_best: int = 0
        self._rhythm_last_max_score: int = 0
        self._rhythm_last_difficulty: str = "easy"

        # Pico → Pi handshake:
        self._pico_best_score_done: bool = False

        # How long to show Pi-controlled difficulty colors after best score is done
        self._pi_mode_colors_hold_sec: float = 2

    @property
    def current_mode_name(self) -> str:
        return self.current_mode

    def _get_audio_engine(self):
        for mode in (self.piano, self.rhythm, self.song):
            audio = getattr(mode, "audio", None)
            if audio is not None:
                return audio
        return None

    def _rhythm_is_in_postgame(self) -> bool:
        return bool(self._rhythm_postgame_started and self._rhythm_postgame_stage is not None)

    def _render_pi_difficulty_colors(self) -> None:
        # Preferred: future public method
        if hasattr(self.rhythm, "show_mode_colors"):
            try:
                self.rhythm.show_mode_colors()
                return
            except Exception as e:
                print("[InputManager] rhythm.show_mode_colors error:", e)

        # Fallback: reuse existing renderer
        if hasattr(self.rhythm, "_render_wait_countdown"):
            try:
                self.rhythm._render_wait_countdown()
                return
            except Exception as e:
                print("[InputManager] rhythm._render_wait_countdown error:", e)

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

        if self.current_mode == "rhythm":
            if hasattr(self.rhythm, "on_exit"):
                self.rhythm.on_exit()
            self._rhythm_postgame_started = False
            self._rhythm_postgame_stage = None
            self._pico_best_score_done = False

        self.current_mode = mode_name
        print(f"[MODE] Switched to: {self.current_mode.upper()}")

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
            self._pico_best_score_done = False
            self.rhythm.reset(now)

        elif mode_name == "song":
            self.song.reset(now)

        if self.pico_display is not None:
            try:
                self.pico_display.show_mode(mode_name)
            except Exception as e:
                print("[InputManager] pico_display.show_mode error:", e)

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
            return

        if up.startswith("RHYTHM:BEST_SCORE_DONE"):
            if self.current_mode == "rhythm":
                print("[InputManager] Pico → RHYTHM:BEST_SCORE_DONE")
                self._pico_best_score_done = True
            return

    def handle_events(self, events: List[InputEvent], now: float) -> None:
        for ev in events:
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
            if self._rhythm_is_in_postgame():
                return
            self._handle_rhythm_events(events, now)

        elif self.current_mode == "song":
            if hasattr(self.song, "handle_events"):
                self.song.handle_events(events)

    def _handle_rhythm_events(self, events: List[InputEvent], now: float) -> None:
        phase = getattr(self.rhythm, "phase", None)

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

                if self.pico_display is not None:
                    try:
                        self.pico_display.send_rhythm_level(difficulty)
                    except Exception as e:
                        print("[InputManager] pico_display.send_rhythm_level error:", e)

                return
            return

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

    def _maybe_run_rhythm_postgame_timeline(self, now: float) -> None:
        phase = getattr(self.rhythm, "phase", None)

        if phase != "DONE":
            self._rhythm_postgame_started = False
            self._rhythm_postgame_stage = None
            self._pico_best_score_done = False
            return

        if self.pico_display is None:
            return

        if not self._rhythm_postgame_started:
            self._rhythm_postgame_started = True
            self._rhythm_postgame_stage = "result_scroll"
            self._rhythm_postgame_t0 = now
            self._pico_best_score_done = False

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

        stage = self._rhythm_postgame_stage
        elapsed = now - self._rhythm_postgame_t0

        if stage == "result_scroll":
            if elapsed >= 4.0:
                try:
                    self.pico_display.send_rhythm_user_score_label()
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_user_score_label error:", e)
                self._rhythm_postgame_stage = "user_label"
                self._rhythm_postgame_t0 = now

        elif stage == "user_label":
            if elapsed >= 3.0:
                score = self._rhythm_last_score
                max_score = self._rhythm_last_max_score
                user_text = f"{score}/{max_score}" if max_score > 0 else str(score)
                try:
                    self.pico_display.send_rhythm_user_score(user_text)
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_user_score error:", e)
                self._rhythm_postgame_stage = "user_score"
                self._rhythm_postgame_t0 = now

        elif stage == "user_score":
            if elapsed >= 3.0:
                try:
                    self.pico_display.send_rhythm_best_score_label()
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_best_score_label error:", e)
                self._rhythm_postgame_stage = "best_label"
                self._rhythm_postgame_t0 = now

        elif stage == "best_label":
            if elapsed >= 1.0:
                best = self._rhythm_last_best
                max_score = self._rhythm_last_max_score
                best_text = f"{best}/{max_score}" if max_score > 0 else str(best)
                try:
                    self.pico_display.send_rhythm_best_score(best_text)
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_best_score error:", e)
                self._rhythm_postgame_stage = "best_score_wait_done"
                self._rhythm_postgame_t0 = now

        elif stage == "best_score_wait_done":
            if self._pico_best_score_done:
                self._rhythm_postgame_stage = "pi_mode_colors_hold"
                self._rhythm_postgame_t0 = now

        elif stage == "pi_mode_colors_hold":
            if elapsed >= float(self._pi_mode_colors_hold_sec):
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
                self._pico_best_score_done = False

    def update(self, now: float) -> None:
        # 1) Poll Pico messages
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
            # ✅ 關鍵：post-game (phase==DONE) 時不要再呼叫 rhythm.update()
            # 否則 RhythmMode(DONE) 每幀 clear_all()+show() 會跟我們 repaint 打架，造成閃爍
            phase = getattr(self.rhythm, "phase", None)
            in_postgame = (phase == "DONE" and self._rhythm_is_in_postgame())

            if not in_postgame:
                if hasattr(self.rhythm, "update"):
                    self.rhythm.update(now)

            # Post-game controller (仍要跑)
            self._maybe_run_rhythm_postgame_timeline(now)

            # 在 hold 期間，由 InputManager 單獨輸出畫面（不給 RhythmMode 參與）
            if self._rhythm_postgame_stage == "pi_mode_colors_hold":
                self._render_pi_difficulty_colors()

        elif self.current_mode == "song":
            if hasattr(self.song, "update"):
                self.song.update(now)
