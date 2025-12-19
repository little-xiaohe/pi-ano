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

    Protocol (Pi → Pico), one command per line:
      MODE:menu
      MODE:piano
      MODE:rhythm
      MODE:song

      RHYTHM:COUNTDOWN            # ask Pico to show 5→1 countdown
      RHYTHM:INGAME               # ask Pico to show in-game RYTHM.bmp
      RHYTHM:RESULT:x/y           # optional final score

      RHYTHM:LEVEL:easy|medium|hard

      # Post-game flow:
      RHYTHM:CHALLENGE_FAIL       # scroll "CHALLENGE FAIL"
      RHYTHM:CHALLENGE_SUCCESS    # scroll "NEW RECORD!"
      RHYTHM:USER_SCORE_LABEL     # scroll "YOUR SCORE"
      RHYTHM:USER_SCORE:x/y       # show this run score
      RHYTHM:BEST_SCORE_LABEL     # scroll "BEST SCORE"
      RHYTHM:BEST_SCORE:x/y       # show best score
      RHYTHM:BACK_TO_TITLE        # back to rhythm title → select

    Shutdown / utility:
      LED:CLEAR                   # clear/turn off the Pico-controlled LED panel
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
            print("[PicoModeDisplay] disabled (no serial module or disabled flag)")
            return

        try:
            self.ser = serial.Serial(
                device,
                baudrate=baudrate,
                timeout=0,  # non-blocking
            )

            # Give Pico time to reboot/reset after opening the port.
            # Without this delay, the first commands may be lost.
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
        """Close the serial connection."""
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def _send_line(self, line: str) -> None:
        """Send one newline-terminated command line to Pico."""
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

    def clear(self) -> None:
        """
        Clear/turn off the Pico-controlled LED display.

        Pico-side code.py should handle:
          LED:CLEAR
        """
        self._send_line("LED:CLEAR")

    def show_mode(self, mode_name: str) -> None:
        """Send MODE:<name> to Pico (menu/piano/rhythm/song)."""
        self._send_line(f"MODE:{mode_name}")

    def send_rhythm_countdown(self) -> None:
        """Ask Pico to start the 5→1 countdown animation."""
        self._send_line("RHYTHM:COUNTDOWN")

    def send_rhythm_ingame(self) -> None:
        """Tell Pico that rhythm gameplay is in progress."""
        self._send_line("RHYTHM:INGAME")

    def send_rhythm_result(self, score: int, max_score: int) -> None:
        """Optionally tell Pico the final score x/y."""
        self._send_line(f"RHYTHM:RESULT:{score}/{max_score}")

    def poll_messages(self) -> List[str]:
        """
        Non-blocking read of any lines printed by Pico.

        Returns:
            A list of complete lines (without trailing newline).
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

            # Extract complete lines from the buffer.
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
        """Tell Pico the selected difficulty so it can show EASY/MEDIUM/HARD."""
        diff = difficulty.strip().lower()
        self._send_line(f"RHYTHM:LEVEL:{diff}")

    # --------------------------------------------------------------
    # Post-game helpers: result banners / score screens / return-to-title
    # --------------------------------------------------------------

    def send_rhythm_challenge_fail(self) -> None:
        """Scroll 'CHALLENGE FAIL'."""
        self._send_line("RHYTHM:CHALLENGE_FAIL")

    def send_rhythm_challenge_success(self) -> None:
        """Scroll 'NEW RECORD!'."""
        self._send_line("RHYTHM:CHALLENGE_SUCCESS")

    def send_rhythm_user_score_label(self) -> None:
        """Scroll 'YOUR SCORE'."""
        self._send_line("RHYTHM:USER_SCORE_LABEL")

    def send_rhythm_user_score(self, score_text: str) -> None:
        """Show this run score (string), e.g., '0/84'."""
        self._send_line(f"RHYTHM:USER_SCORE:{score_text}")

    def send_rhythm_best_score_label(self) -> None:
        """Scroll 'BEST SCORE'."""
        self._send_line("RHYTHM:BEST_SCORE_LABEL")

    def send_rhythm_best_score(self, best_text: str) -> None:
        """Show best score (string), e.g., '67/84'."""
        self._send_line(f"RHYTHM:BEST_SCORE:{best_text}")

    def send_rhythm_back_to_title(self) -> None:
        """
        Return to the rhythm title screen:

          - Pico shows RYTHM.bmp for ~3 seconds
          - Then Pico automatically enters the SELECT bitmap cycle
        """
        self._send_line("RHYTHM:BACK_TO_TITLE")
