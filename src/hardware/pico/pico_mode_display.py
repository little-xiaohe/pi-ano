from __future__ import annotations

import time
from typing import List, Optional

try:
    import serial  # pyserial
except ImportError:
    serial = None


class PicoModeDisplay:
    """
    Small helper for talking to the Pico over USB serial.

    Protocol (Pi → Pico):
      MODE:menu
      MODE:piano
      MODE:rhythm
      MODE:song

      RHYTHM:COUNTDOWN            # ask Pico to show 5→1 countdown
      RHYTHM:INGAME               # ask Pico to show in-game RYTHM.bmp
      RHYTHM:RESULT:x/y           # (原本用不到可留著)

      RHYTHM:LEVEL:easy|medium|hard

      # Post-game:
      RHYTHM:CHALLENGE_FAIL       # scroll "CHALLENGE FAIL"
      RHYTHM:CHALLENGE_SUCCESS    # scroll "NEW RECORD!"
      RHYTHM:USER_SCORE_LABEL     # scroll "YOUR SCORE"
      RHYTHM:USER_SCORE:x/y       # show this run score
      RHYTHM:BEST_SCORE_LABEL     # scroll "BEST SCORE"
      RHYTHM:BEST_SCORE:x/y       # show best score
      RHYTHM:BACK_TO_TITLE        # back to rhythm title → select
    """

    def __init__(
        self,
        device: str = "/dev/ttyACM0",
        baudrate: int = 115200,
        enabled: bool = True,
    ) -> None:
        self.device = device
        self.baudrate = baudrate
        self.enabled = enabled and (serial is not None)
        self.ser: Optional[serial.Serial] = None
        self._rx_buffer: str = ""

        if not self.enabled:
            print("[PicoModeDisplay] disabled (no serial or disabled flag)")
            return

        try:
            self.ser = serial.Serial(
                device,
                baudrate=baudrate,
                timeout=0,        # non-blocking
            )
            # 等 Pico reset 完成，不然一開始資料容易丟
            time.sleep(2.0)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            print(f"[PicoModeDisplay] opened {device} @ {baudrate}")
        except Exception as e:
            print(f"[PicoModeDisplay] FAILED to open {device}: {e}")
            self.ser = None
            self.enabled = False

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def _send_line(self, line: str) -> None:
        """Send one line (append '\n') to Pico."""
        if not self.enabled or self.ser is None:
            return
        try:
            text = line.strip()
            data = (text + "\n").encode("utf-8")
            self.ser.write(data)
            self.ser.flush()
            print(f"[Pico >>] {text}")
        except Exception as e:
            print("[PicoModeDisplay] write error:", e)

    # ------------------------------------------------------------------
    # Public API used by InputManager / main.py
    # ------------------------------------------------------------------

    def show_mode(self, mode_name: str) -> None:
        """MODE:menu / MODE:piano / MODE:rhythm / MODE:song"""
        self._send_line(f"MODE:{mode_name}")

    def send_rhythm_countdown(self) -> None:
        """Ask Pico to start 5→1 countdown."""
        self._send_line("RHYTHM:COUNTDOWN")

    def send_rhythm_ingame(self) -> None:
        """Tell Pico that rhythm game is now playing (show RYTHM.bmp)."""
        self._send_line("RHYTHM:INGAME")

    def send_rhythm_result(self, score: int, max_score: int) -> None:
        """(可選) 告訴 Pico 最終分數 x/y。"""
        self._send_line(f"RHYTHM:RESULT:{score}/{max_score}")

    def poll_messages(self) -> List[str]:
        """
        Non-blocking read of any lines Pico printed.

        Returns a list of complete lines (without '\n').
        """
        if not self.enabled or self.ser is None:
            return []

        msgs: List[str] = []
        try:
            n = self.ser.in_waiting
            if n <= 0:
                return []

            data = self.ser.read(n).decode("utf-8", errors="ignore")
            if not data:
                return []

            self._rx_buffer += data

            # 把 buffer 中的完整行切出來
            while "\n" in self._rx_buffer:
                line, self._rx_buffer = self._rx_buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                print(f"[Pico <<] {line}")
                msgs.append(line)

        except Exception as e:
            print("[PicoModeDisplay] read error:", e)

        return msgs

    def send_rhythm_level(self, difficulty: str) -> None:
        """
        告訴 Pico 目前的難度，讓它顯示 HARD / MEDIUM / EASY。
        """
        if not self.enabled or self.ser is None:
            return
        diff = difficulty.lower()
        self._send_line(f"RHYTHM:LEVEL:{diff}")

    # --------------------------------------------------------------
    # 新增：挑戰結果 / 分數顯示 / 回到 title
    # --------------------------------------------------------------

    def send_rhythm_challenge_fail(self) -> None:
        """挑戰失敗：'CHALLENGE FAIL' 跑馬燈。"""
        self._send_line("RHYTHM:CHALLENGE_FAIL")

    def send_rhythm_challenge_success(self) -> None:
        """挑戰成功（新紀錄）：'NEW RECORD!' 跑馬燈。"""
        self._send_line("RHYTHM:CHALLENGE_SUCCESS")

    def send_rhythm_user_score_label(self) -> None:
        """跑馬燈 'YOUR SCORE'。"""
        self._send_line("RHYTHM:USER_SCORE_LABEL")

    def send_rhythm_user_score(self, score_text: str) -> None:
        """
        顯示這一局分數（用字串，例：'0/84'）。
        """
        self._send_line(f"RHYTHM:USER_SCORE:{score_text}")

    def send_rhythm_best_score_label(self) -> None:
        """跑馬燈 'BEST SCORE'。"""
        self._send_line("RHYTHM:BEST_SCORE_LABEL")

    def send_rhythm_best_score(self, best_text: str) -> None:
        """
        顯示歷史最高分（用字串，例：'67/84'）。
        """
        self._send_line(f"RHYTHM:BEST_SCORE:{best_text}")

    def send_rhythm_back_to_title(self) -> None:
        """
        回到 rhythm mode 最一開始畫面：
          - Pico 顯示 RYTHM.bmp 3 秒
          - 再自動進入 SELECT BMP 循環
        """
        self._send_line("RHYTHM:BACK_TO_TITLE")
