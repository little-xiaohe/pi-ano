# src/hardware/pico/pico_mode_display.py

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

      RHYTHM:COUNTDOWN      # ask Pico to show 5→1 countdown
      RHYTHM:INGAME         # ask Pico to show in-game RYTHM.bmp
      RHYTHM:RESULT:x/y     # show final score

    Pico (→ Pi) will print e.g.:
      RHYTHM:COUNTDOWN_DONE
    which we poll via poll_messages() and forward to InputManager.
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
            # 等 Pico reset 好，不然一開始的資料容易丟
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
        """Tell Pico to show final score."""
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
                print(f"[Pico <<] {line}")  # ★ debug：看到 Pico 回了什麼
                msgs.append(line)

        except Exception as e:
            print("[PicoModeDisplay] read error:", e)

        return msgs

    def send_rhythm_level(self, difficulty: str) -> None:
        """
        告訴 Pico 目前的難度，讓它顯示 HARD / MEDIUM / EASY。
        會送出：
          RHYTHM:LEVEL:easy | medium | hard
        """
        if not self.enabled or self.ser is None:
            return
        diff = difficulty.lower()
        self._send_line(f"RHYTHM:LEVEL:{diff}")
