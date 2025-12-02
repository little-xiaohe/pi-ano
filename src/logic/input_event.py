# src/logic/input_event.py

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from src.hardware.config.keys import KeyId


class EventType(Enum):
    NOTE_ON = auto()
    NOTE_OFF = auto()
    MODE_SWITCH = auto()
    NEXT_SONG = auto()   # ← 一定要有這個


@dataclass
class InputEvent:
    type: EventType

    # for NOTE_ON / NOTE_OFF
    key: Optional[KeyId] = None
    velocity: float = 1.0

    # for MODE_SWITCH
    mode_name: Optional[str] = None
