# src/hardware/config/keys.py
"""
Central definition of piano key IDs and their LED zones.

- Which keys exist (KeyId enum).
- Where each key is located on the LED matrix (KEY_ZONES).
- Optional debug colors for each key (KEY_COLORS).
"""

from enum import IntEnum
from typing import Dict, Tuple, List


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
# Predefined color palettes for the 5 keys (for piano/song modes)
# Each palette is: Dict[KeyId, (R, G, B)]
# ---------------------------------------------------------------------------

# 30 curated palettes for 5-key LED piano
KEY_COLOR_PALETTES = [

    # 1 — Pastel Aurora (柔光極光)
    {
        KeyId.KEY_0: (122, 31, 42),   #3B0D11 (Rich Mahogany)
        KeyId.KEY_1: (168, 99, 43),   #6A3937 (Bitter Chocolate)
        KeyId.KEY_2: (74, 127, 63),   #706563 (Dim Grey)
        KeyId.KEY_3: (62, 114, 140),   #748386 (Slate Grey)
        KeyId.KEY_4: (100, 64, 125),   #9DC7C8 (Light Blue)
    },
]
