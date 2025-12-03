# src/logic/input_event.py

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from src.hardware.config.keys import KeyId


class EventType(Enum):
    NOTE_ON = auto()
    NOTE_OFF = auto()
    MODE_SWITCH = auto()   # keyboard: mode piano / mode song ...
    NEXT_SONG = auto()     # keyboard: next （song mode 用）
    NEXT_MODE = auto()     # button: 長按 D14 → 切到下一個 mode


@dataclass
class InputEvent:
    type: EventType

    # 對 NOTE_ON / NOTE_OFF 有用
    key: Optional[KeyId] = None
    velocity: float = 1.0

    # 對 MODE_SWITCH 有用
    mode_name: Optional[str] = None

    # 來源標記（"keyboard" / "button" / "ir"...），可以不填
    source: Optional[str] = None

