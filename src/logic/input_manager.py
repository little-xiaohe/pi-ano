# src/logic/input_manager.py

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

        # Rhythm high scores + post-game timeline 狀態
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

        # 離開舊 mode
        if self.current_mode == "rhythm":
            if hasattr(self.rhythm, "on_exit"):
                self.rhythm.on_exit()
            self._rhythm_postgame_started = False
            self._rhythm_postgame_stage = None

        self.current_mode = mode_name
        print(f"[MODE] Switched to: {self.current_mode.upper()}")

        # 進入新 mode
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
            self.rhythm.reset(now)

        elif mode_name == "song":
            self.song.reset(now)

        # 通知 Pico 切換模式
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

                if self.pico_display is not None:
                    try:
                        difficulty = getattr(self.rhythm, "difficulty", "easy")
                        self.pico_display.send_rhythm_level(difficulty)
                    except Exception as e:
                        print("[InputManager] pico_display.send_rhythm_level error:", e)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_events(self, events: List[InputEvent], now: float) -> None:
        # 1) 全域事件：mode switch / next mode
        for ev in events:
            if ev.type == EventType.MODE_SWITCH and ev.mode_name:
                self._switch_mode(ev.mode_name, now)
                continue

            if ev.type == EventType.NEXT_MODE:
                self._cycle_mode(now)
                continue

            # ★ 不在這裡處理 NEXT_SONG，讓 song mode 自己看 D24 / NEXT_SONG
            #   事件原封不動傳給 self.song.handle_events(events)

        # 2) mode-specific
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
                # ★ 把所有事件（包含 D24 NOTE_ON）傳給 MidiSongMode
                self.song.handle_events(events)

    # ------------------------------------------------------------------
    # Rhythm-specific events
    # ------------------------------------------------------------------

    def _handle_rhythm_events(self, events: List[InputEvent], now: float) -> None:
        phase = getattr(self.rhythm, "phase", None)

        # WAIT_COUNTDOWN：選難度
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
                        self.pico_display.send_rhythm_countdown()
                    except Exception as e:
                        print("[InputManager] pico_display.send_rhythm_countdown error:", e)

                return

            return

        # PLAY：按鍵當成 hit
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

        # DONE / 其他：不處理事件
        return

    # ------------------------------------------------------------------
    # Rhythm post-game timeline（Pi 控制整個節奏）
    # ------------------------------------------------------------------

    def _maybe_run_rhythm_postgame_timeline(self, now: float) -> None:
        """
        phase == DONE 之後：

          第一次看到 DONE：
            - 讀 score / max_score / difficulty
            - update high score
            - 送 CHALLENGE_FAIL or CHALLENGE_SUCCESS （跑馬燈一）
            - stage = "result_scroll"

          接著時間線：
            "result_scroll" 5.5s  → 送 USER_SCORE_LABEL   (YOUR SCORE 跑馬燈)
            "user_label"    4.0s  → 送 USER_SCORE        (顯示 x/y)
            "user_score"    3.0s  → 送 BEST_SCORE_LABEL  (BEST SCORE 跑馬燈)
            "best_label"    4.0s  → 送 BEST_SCORE        (顯示 best/y)
            "best_score"    3.0s  → 送 BACK_TO_TITLE 並 reset rhythm()
        """
        phase = getattr(self.rhythm, "phase", None)

        if phase != "DONE":
            self._rhythm_postgame_started = False
            self._rhythm_postgame_stage = None
            return

        if self.pico_display is None:
            return

        # ---- 第一次看到 DONE：初始化 ----
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

        # ---- 之後依 stage + elapsed 控制 ----
        stage = self._rhythm_postgame_stage
        elapsed = now - self._rhythm_postgame_t0

        # 1) FAIL / NEW RECORD! 跑馬燈：給長一點時間（約 5.5 秒）
        if stage == "result_scroll":
            if elapsed >= 3.0:
                try:
                    self.pico_display.send_rhythm_user_score_label()
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_user_score_label error:", e)
                self._rhythm_postgame_stage = "user_label"
                self._rhythm_postgame_t0 = now

        # 2) YOUR SCORE 跑馬燈：4 秒
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

        # 3) 顯示 0/84 靜態 3 秒
        elif stage == "user_score":
            if elapsed >= 3.0:
                try:
                    self.pico_display.send_rhythm_best_score_label()
                except Exception as e:
                    print("[InputManager] pico_display.send_rhythm_best_score_label error:", e)
                self._rhythm_postgame_stage = "best_label"
                self._rhythm_postgame_t0 = now

        # 4) BEST SCORE 跑馬燈：4 秒
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

        # 5) 顯示最高分靜態 3 秒 → 回 title + reset
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
        if self.pico_display is not None:
            try:
                messages = self.pico_display.poll_messages()
            except Exception as e:
                print("[InputManager] pico_display.poll_messages error:", e)
                messages = []

            for msg in messages:
                self._handle_pico_message(msg, now)

        if self.current_mode == "menu":
            if hasattr(self.menu, "update"):
                self.menu.update(now)

        elif self.current_mode == "piano":
            if hasattr(self.piano, "update"):
                self.piano.update(now)

        elif self.current_mode == "rhythm":
            if hasattr(self.rhythm, "update"):
                self.rhythm.update(now)
            # ★ 節奏遊戲結束的 post-game 美術效果
            self._maybe_run_rhythm_postgame_timeline(now)

        elif self.current_mode == "song":
            if hasattr(self.song, "update"):
                self.song.update(now)
