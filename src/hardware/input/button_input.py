# src/hardware/input/button_input.py

import time
from dataclasses import dataclass
from typing import List, Dict

import board
import digitalio

from src.logic.input_event import InputEvent, EventType


@dataclass
class ButtonChannel:
    name: str
    pin: digitalio.DigitalInOut
    last_value: bool  # True = released (pull-up), False = pressed


class ButtonInput:
    """
    Read physical buttons on GPIO and convert them into InputEvent(s).

    Wiring (pull-up inputs, active LOW):

      - D14 → "chiikawa" mode
      - D15 → "piano"    mode
      - D18 → "rhythm"   mode
      - D24 → "song / next song" button
              - 若目前不在 song mode，視為「切到 song mode」
              - 若目前在 song mode，視為「跳下一首」

    注意：
      - 這裡只做「按下瞬間」的 edge detect（HIGH → LOW）
      - 去抖動目前先簡單用狀態判斷；如果有需要可以再加時間 filter
    """

    def __init__(self, debug: bool = True) -> None:
        self.debug = debug

        # 建立 DigitalInOut
        pin_map: Dict[str, board.Pin] = {
            "chiikawa": board.D14,
            "piano": board.D15,
            "rhythm": board.D18,
            "song_next": board.D24,
        }

        self.channels: Dict[str, ButtonChannel] = {}

        for name, pin_obj in pin_map.items():
            dio = digitalio.DigitalInOut(pin_obj)
            dio.direction = digitalio.Direction.INPUT
            dio.pull = digitalio.Pull.UP  # 使用內建上拉，按下時變 LOW
            ch = ButtonChannel(
                name=name,
                pin=dio,
                last_value=True,  # 一開始假設都「沒按」（HIGH）
            )
            self.channels[name] = ch

        # 如果之後要做更強的 debounce，可以再加 timestamp
        # self.last_change_time = {name: 0.0 for name in self.channels}

    def _on_button_pressed(self, name: str) -> List[InputEvent]:
        events: List[InputEvent] = []

        if name == "chiikawa":
            events.append(InputEvent(type=EventType.MODE_SWITCH, mode_name="chiikawa"))

        elif name == "piano":
            events.append(InputEvent(type=EventType.MODE_SWITCH, mode_name="piano"))

        elif name == "rhythm":
            events.append(InputEvent(type=EventType.MODE_SWITCH, mode_name="rhythm"))

        elif name == "song_next":
            # 解讀交給 InputManager
            events.append(InputEvent(type=EventType.NEXT_SONG))

        return events


    def poll(self) -> List[InputEvent]:
        """
        掃描所有按鈕，對「從未按 → 按下」的瞬間產生事件。
        """
        events: List[InputEvent] = []

        for name, ch in self.channels.items():
            current = ch.pin.value  # True = released, False = pressed

            # edge detection: HIGH → LOW = "按下"
            if ch.last_value and (not current):
                # 按下瞬間
                events.extend(self._on_button_pressed(name))

            # 更新 last_value
            ch.last_value = current

        return events
