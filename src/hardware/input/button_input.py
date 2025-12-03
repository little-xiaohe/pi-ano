# src/hardware/input/button_input.py

import time
from dataclasses import dataclass
from typing import List

import board
import digitalio

from src.logic.input_event import InputEvent, EventType
from src.hardware.config.keys import KeyId


LONG_PRESS_SEC = 1.0  # 長按多久算「切 mode」


@dataclass
class ButtonChannel:
    """
    One physical button mapped to one KeyId.
    """
    key: KeyId
    pin: digitalio.DigitalInOut
    last_value: bool          # True = released (pull-up), False = pressed
    press_time: float | None  # 按下當下的時間戳
    long_sent: bool           # 是否已經送過 NEXT_MODE（避免重複）


class ButtonInput:
    """
    Read physical buttons on GPIO and convert them into InputEvent(s).

    Wiring (pull-up inputs, active LOW):

      KEY_0 → D25
      KEY_1 → D24
      KEY_2 → D18
      KEY_3 → D15
      KEY_4 → D14  ← 長按這顆可以「切到下一個 mode」

    規則：
      - 短按：NOTE_ON / NOTE_OFF（在 rhythm mode 當 hit 用）
      - 任一 mode 下長按 KEY_4(D14) ≥ LONG_PRESS_SEC：
          → 送出 EventType.NEXT_MODE
    """

    def __init__(self, debug: bool = True) -> None:
        self.debug = debug

        # (KeyId, GPIO pin)
        key_pin_pairs = [
            (KeyId.KEY_0, board.D25),
            (KeyId.KEY_1, board.D24),
            (KeyId.KEY_2, board.D18),
            (KeyId.KEY_3, board.D15),
            (KeyId.KEY_4, board.D14),
        ]

        self.channels: List[ButtonChannel] = []

        for key, pin_obj in key_pin_pairs:
            dio = digitalio.DigitalInOut(pin_obj)
            dio.direction = digitalio.Direction.INPUT
            dio.pull = digitalio.Pull.UP  # 使用內建上拉，按下時變 LOW
            ch = ButtonChannel(
                key=key,
                pin=dio,
                last_value=True,      # 一開始假設都「沒按」（HIGH）
                press_time=None,
                long_sent=False,
            )
            self.channels.append(ch)

    def poll(self) -> List[InputEvent]:
        """
        掃描所有按鈕，產生：
          - 按下瞬間        → NOTE_ON
          - 放開瞬間        → NOTE_OFF
          - D14 長按超過門檻 → NEXT_MODE
        """
        events: List[InputEvent] = []
        now = time.monotonic()

        for ch in self.channels:
            current = ch.pin.value  # True = released, False = pressed

            # --- edge: HIGH -> LOW = press ---
            if ch.last_value and (not current):
                ch.press_time = now
                ch.long_sent = False

                # 立刻送出 NOTE_ON（給 rhythm mode 當 hit 用）
                ev = InputEvent(
                    type=EventType.NOTE_ON,
                    key=ch.key,
                    velocity=1.0,
                    source="button",
                )
                events.append(ev)
                if self.debug:
                    print(f"[BTN] NOTE_ON key={int(ch.key)}")

            # --- still pressed: check long press for KEY_4 (D14) ---
            if (not current) and ch.press_time is not None:
                # still pressed
                if (ch.key == KeyId.KEY_4) and (not ch.long_sent):
                    duration = now - ch.press_time
                    if duration >= LONG_PRESS_SEC:
                        # 送出 NEXT_MODE（切換到下一個 mode）
                        ev = InputEvent(
                            type=EventType.NEXT_MODE,
                            source="button",
                        )
                        events.append(ev)
                        ch.long_sent = True
                        if self.debug:
                            print("[BTN] LONG PRESS on KEY_4 → NEXT_MODE")

            # --- edge: LOW -> HIGH = release ---
            if (not ch.last_value) and current:
                # 放開瞬間：NOTE_OFF
                ev = InputEvent(
                    type=EventType.NOTE_OFF,
                    key=ch.key,
                    velocity=1.0,
                    source="button",
                )
                events.append(ev)
                if self.debug:
                    print(f"[BTN] NOTE_OFF key={int(ch.key)}")

                # reset press info
                ch.press_time = None
                ch.long_sent = False

            ch.last_value = current

        return events
