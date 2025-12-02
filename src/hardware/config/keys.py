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
        KeyId.KEY_0: (180, 220, 255),
        KeyId.KEY_1: (200, 235, 255),
        KeyId.KEY_2: (220, 245, 255),
        KeyId.KEY_3: (200, 255, 230),
        KeyId.KEY_4: (180, 245, 210),
    },

    # 2 — Sunset Bloom (落日粉橙)
    {
        KeyId.KEY_0: (255, 170, 190),
        KeyId.KEY_1: (255, 190, 180),
        KeyId.KEY_2: (255, 210, 170),
        KeyId.KEY_3: (255, 230, 180),
        KeyId.KEY_4: (255, 245, 200),
    },

    # 3 — Ocean Mist
    {
        KeyId.KEY_0: (150, 200, 255),
        KeyId.KEY_1: (130, 220, 255),
        KeyId.KEY_2: (110, 240, 255),
        KeyId.KEY_3: (100, 255, 230),
        KeyId.KEY_4: (90, 240, 200),
    },

    # 4 — Candy Pastel
    {
        KeyId.KEY_0: (255, 180, 200),
        KeyId.KEY_1: (255, 160, 220),
        KeyId.KEY_2: (240, 150, 255),
        KeyId.KEY_3: (200, 150, 255),
        KeyId.KEY_4: (160, 140, 255),
    },

    # 5 — Ice Cream Sherbet
    {
        KeyId.KEY_0: (255, 200, 180),
        KeyId.KEY_1: (255, 220, 160),
        KeyId.KEY_2: (255, 230, 180),
        KeyId.KEY_3: (255, 240, 210),
        KeyId.KEY_4: (240, 255, 220),
    },

    # 6 — Tropical Neon
    {
        KeyId.KEY_0: (255, 90, 120),
        KeyId.KEY_1: (255, 140, 80),
        KeyId.KEY_2: (255, 200, 50),
        KeyId.KEY_3: (140, 255, 80),
        KeyId.KEY_4: (80, 230, 255),
    },

    # 7 — Sakura Breeze
    {
        KeyId.KEY_0: (255, 200, 220),
        KeyId.KEY_1: (255, 180, 210),
        KeyId.KEY_2: (255, 160, 190),
        KeyId.KEY_3: (255, 140, 170),
        KeyId.KEY_4: (255, 120, 160),
    },

    # 8 — Mint Garden
    {
        KeyId.KEY_0: (180, 255, 210),
        KeyId.KEY_1: (160, 250, 200),
        KeyId.KEY_2: (140, 240, 190),
        KeyId.KEY_3: (120, 230, 180),
        KeyId.KEY_4: (110, 220, 170),
    },

    # 9 — Deep Ocean Blue
    {
        KeyId.KEY_0: (100, 150, 255),
        KeyId.KEY_1: (80, 130, 240),
        KeyId.KEY_2: (60, 110, 225),
        KeyId.KEY_3: (50, 90, 210),
        KeyId.KEY_4: (40, 70, 190),
    },

    # 10 — Galaxy Core
    {
        KeyId.KEY_0: (255, 140, 200),
        KeyId.KEY_1: (200, 120, 255),
        KeyId.KEY_2: (150, 100, 255),
        KeyId.KEY_3: (110, 80, 240),
        KeyId.KEY_4: (80, 60, 220),
    },

    # 11 — Lemon Lime Soda
    {
        KeyId.KEY_0: (210, 255, 100),
        KeyId.KEY_1: (180, 255, 120),
        KeyId.KEY_2: (150, 255, 140),
        KeyId.KEY_3: (120, 255, 160),
        KeyId.KEY_4: (100, 255, 180),
    },

    # 12 — Dawn Horizon
    {
        KeyId.KEY_0: (255, 190, 170),
        KeyId.KEY_1: (255, 160, 140),
        KeyId.KEY_2: (255, 130, 110),
        KeyId.KEY_3: (255, 100, 90),
        KeyId.KEY_4: (230, 80, 70),
    },

    # 13 — Retro Arcade
    {
        KeyId.KEY_0: (255, 60, 60),
        KeyId.KEY_1: (255, 160, 60),
        KeyId.KEY_2: (255, 255, 60),
        KeyId.KEY_3: (100, 255, 80),
        KeyId.KEY_4: (60, 200, 255),
    },

    # 14 — Ice Blue Glacier
    {
        KeyId.KEY_0: (180, 220, 250),
        KeyId.KEY_1: (160, 210, 240),
        KeyId.KEY_2: (140, 200, 230),
        KeyId.KEY_3: (120, 190, 220),
        KeyId.KEY_4: (100, 180, 210),
    },

    # 15 — Fairy Ribbon
    {
        KeyId.KEY_0: (255, 160, 255),
        KeyId.KEY_1: (240, 150, 255),
        KeyId.KEY_2: (220, 140, 255),
        KeyId.KEY_3: (200, 130, 255),
        KeyId.KEY_4: (190, 120, 250),
    },

    # 16 — Watermelon Mix
    {
        KeyId.KEY_0: (255, 90, 120),
        KeyId.KEY_1: (255, 110, 150),
        KeyId.KEY_2: (255, 130, 180),
        KeyId.KEY_3: (255, 150, 210),
        KeyId.KEY_4: (255, 170, 230),
    },

    # 17 — Cool Mint Punch
    {
        KeyId.KEY_0: (160, 255, 200),
        KeyId.KEY_1: (140, 255, 180),
        KeyId.KEY_2: (120, 255, 160),
        KeyId.KEY_3: (100, 255, 140),
        KeyId.KEY_4: (80, 255, 120),
    },

    # 18 — Soda Pop Neon
    {
        KeyId.KEY_0: (255, 120, 60),
        KeyId.KEY_1: (255, 160, 60),
        KeyId.KEY_2: (255, 210, 60),
        KeyId.KEY_3: (130, 255, 70),
        KeyId.KEY_4: (60, 240, 255),
    },

    # 19 — Foggy Sky
    {
        KeyId.KEY_0: (200, 220, 240),
        KeyId.KEY_1: (180, 205, 225),
        KeyId.KEY_2: (165, 190, 210),
        KeyId.KEY_3: (150, 175, 195),
        KeyId.KEY_4: (135, 160, 180),
    },

    # 20 — Vaporwave Pastel
    {
        KeyId.KEY_0: (255, 160, 220),
        KeyId.KEY_1: (220, 140, 255),
        KeyId.KEY_2: (150, 160, 255),
        KeyId.KEY_3: (130, 220, 255),
        KeyId.KEY_4: (170, 255, 230),
    },

    # 21 — Earthy Autumn
    {
        KeyId.KEY_0: (230, 160, 80),
        KeyId.KEY_1: (210, 140, 60),
        KeyId.KEY_2: (190, 120, 50),
        KeyId.KEY_3: (170, 100, 40),
        KeyId.KEY_4: (150, 80, 30),
    },

    # 22 — Crystal Rainbow
    {
        KeyId.KEY_0: (255, 150, 200),
        KeyId.KEY_1: (255, 170, 100),
        KeyId.KEY_2: (255, 240, 80),
        KeyId.KEY_3: (120, 255, 100),
        KeyId.KEY_4: (100, 200, 255),
    },

    # 23 — Fresh Forest
    {
        KeyId.KEY_0: (150, 255, 180),
        KeyId.KEY_1: (120, 235, 150),
        KeyId.KEY_2: (90, 210, 120),
        KeyId.KEY_3: (70, 180, 100),
        KeyId.KEY_4: (60, 150, 90),
    },

    # 24 — Soft Rose Garden
    {
        KeyId.KEY_0: (255, 200, 210),
        KeyId.KEY_1: (255, 180, 190),
        KeyId.KEY_2: (255, 160, 170),
        KeyId.KEY_3: (255, 140, 160),
        KeyId.KEY_4: (255, 120, 150),
    },

    # 25 — Deep Royal Blue
    {
        KeyId.KEY_0: (80, 120, 255),
        KeyId.KEY_1: (60, 100, 240),
        KeyId.KEY_2: (50, 85, 220),
        KeyId.KEY_3: (40, 70, 200),
        KeyId.KEY_4: (30, 55, 170),
    },

    # 26 — Candy Pop (RGBY Mint)
    {
        KeyId.KEY_0: (255, 90, 120),
        KeyId.KEY_1: (255, 200, 60),
        KeyId.KEY_2: (120, 255, 80),
        KeyId.KEY_3: (60, 200, 255),
        KeyId.KEY_4: (200, 120, 255),
    },

    # 27 — Lilac Milk
    {
        KeyId.KEY_0: (230, 210, 255),
        KeyId.KEY_1: (210, 190, 255),
        KeyId.KEY_2: (190, 170, 255),
        KeyId.KEY_3: (170, 150, 240),
        KeyId.KEY_4: (150, 130, 220),
    },

    # 28 — Sky Gradient
    {
        KeyId.KEY_0: (200, 230, 255),
        KeyId.KEY_1: (180, 220, 255),
        KeyId.KEY_2: (160, 210, 255),
        KeyId.KEY_3: (140, 200, 255),
        KeyId.KEY_4: (120, 190, 255),
    },

    # 29 — Golden Pastel
    {
        KeyId.KEY_0: (255, 220, 160),
        KeyId.KEY_1: (255, 205, 140),
        KeyId.KEY_2: (255, 190, 120),
        KeyId.KEY_3: (255, 175, 110),
        KeyId.KEY_4: (255, 160, 100),
    },

    # 30 — Cyber Mint Blue
    {
        KeyId.KEY_0: (150, 240, 255),
        KeyId.KEY_1: (120, 230, 255),
        KeyId.KEY_2: (90, 220, 255),
        KeyId.KEY_3: (70, 210, 255),
        KeyId.KEY_4: (50, 200, 255),
    },
]
