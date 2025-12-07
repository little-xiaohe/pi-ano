# src/hardware/config/keys.py
"""
Central definition of piano key IDs and their LED zones.

- Which keys exist (KeyId enum).
- Where each key is located on the LED matrix (KEY_ZONES).
- Optional debug colors for each key (KEY_COLORS).
"""

from enum import IntEnum
from typing import Dict, Tuple, List
import colorsys


class KeyId(IntEnum):
    """
    Logical piano key identifiers.

    You can rename them to real note names if you want
    (C4, D4, E4, ...), the numeric values are used as indices.
    """
    KEY_0 = 0
    KEY_1 = 1
    KEY_2 = 2
    KEY_3 = 3
    KEY_4 = 4


ALL_KEYS: List[KeyId] = [
    KeyId.KEY_0,
    KeyId.KEY_1,
    KeyId.KEY_2,
    KeyId.KEY_3,
    KeyId.KEY_4,
]

# x = 0 and x = 31 reserved as borders.
# 5 keys use x = 1..30, each key = 6 columns.
KEY_ZONES: Dict[KeyId, Tuple[int, int]] = {
    KeyId.KEY_0: (1, 6),
    KeyId.KEY_1: (7, 12),
    KeyId.KEY_2: (13, 18),
    KeyId.KEY_3: (19, 24),
    KeyId.KEY_4: (25, 30),
}

KEY_COLORS: Dict[KeyId, Tuple[int, int, int]] = {
    KeyId.KEY_0: (122, 31, 42),   #3B0D11 (Rich Mahogany)
    KeyId.KEY_1: (168, 99, 43),   #6A3937 (Bitter Chocolate)
    KeyId.KEY_2: (74, 127, 63),   #706563 (Dim Grey)
    KeyId.KEY_3: (62, 114, 140),   #748386 (Slate Grey)
    KeyId.KEY_4: (100, 64, 125),   #9DC7C8 (Light Blue)
}

# ---------------------------------------------------------------------------
# Dynamic rainbow palette generator (HSV → RGB)
# ---------------------------------------------------------------------------

def _hsv_to_rgb_tuple(h: float, s: float, v: float) -> Tuple[int, int, int]:
    """
    Convert HSV (0.0~1.0) to RGB (0~255).
    """
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def make_rainbow_palette(
    hue_offset: float = 0.0,
    saturation: float = 0.95,
    value: float = 0.95,
) -> Dict[KeyId, Tuple[int, int, int]]:
    """
    Generate a 5-key rainbow palette.

    - hue_offset: base hue shift (0.0 ~ 1.0). Different offsets give
      different rainbow starting colors.
    - saturation / value: brightness & saturation (0.0 ~ 1.0).

    Keys are evenly spaced in hue around the color wheel.
    """
    num_keys = len(ALL_KEYS)
    palette: Dict[KeyId, Tuple[int, int, int]] = {}

    for i, key in enumerate(ALL_KEYS):
        # Evenly spaced hues, with optional offset
        h = (hue_offset + i / num_keys) % 1.0
        palette[key] = _hsv_to_rgb_tuple(h, saturation, value)

    return palette


# ---------------------------------------------------------------------------
# Predefined rainbow palettes (still a list so existing code works)
# You can randomly pick one, or later switch to fully dynamic.
# ---------------------------------------------------------------------------

KEY_COLOR_PALETTES: List[Dict[KeyId, Tuple[int, int, int]]] = [
    make_rainbow_palette(hue_offset=0.00),  # red → orange → green → blue → purple
    make_rainbow_palette(hue_offset=0.10),
    make_rainbow_palette(hue_offset=0.20),
    make_rainbow_palette(hue_offset=0.30),
    make_rainbow_palette(hue_offset=0.40),
    make_rainbow_palette(hue_offset=0.50),
]
