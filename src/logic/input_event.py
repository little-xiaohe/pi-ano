from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from src.hardware.config.keys import KeyId


class EventType(Enum):
    NOTE_ON = auto()
    NOTE_OFF = auto()
    MODE_SWITCH = auto()   # keyboard: mode piano / mode song ...
    NEXT_SONG = auto()     # keyboard: next (used in song mode)
    NEXT_MODE = auto()     # button: long press D14 → switch to next mode
    NEXT_SF2 = auto()      # button: long press D25 (KEY_0) → switch SoundFont


@dataclass
class InputEvent:
    type: EventType

    # For NOTE_ON / NOTE_OFF events
    key: Optional[KeyId] = None
    velocity: float = 1.0

    # For MODE_SWITCH events
    mode_name: Optional[str] = None

    # Source tag ("keyboard" / "button" / "ir"...), optional
    source: Optional[str] = None
