# src/logic/modes/chiikawa_mode.py

import math
import colorsys
from typing import List

from src.hardware.led.led_matrix import LedMatrix
from src.logic.input_event import InputEvent
from src.hardware.config.keys import KeyId



class MenuMode:
    """
    Default menu / home screen mode.

    Visuals:
        - "Pi-ANO" text (colorful, horizontally centered) near the top.
        - Five LED key zones (KEY_0 ~ KEY_4) shown as a soft gradient,
          with a shimmering / wave-like brightness animation.

    NOTE:
        This mode uses a flipped-y helper _set() so that logical (0,0)
        is the TOP-LEFT of the panel.
    """

    def __init__(self, led: LedMatrix) -> None:
        self.led = led
        self.start_time: float | None = None

        # Background color
        self.bg_color = (0, 0, 0)

        # Colorful letters for "Pi-ANO"
        self.text_colors = [
            (255, 120, 120),  # P
            (255, 200, 120),  # i
            (255, 255, 160),  # -
            (150, 230, 150),  # A
            (140, 180, 255),  # N
            (210, 160, 255),  # O
        ]

        # Keys we want to show in menu (5 zones)
        self.menu_keys = [
            KeyId.KEY_0,
            KeyId.KEY_1,
            KeyId.KEY_2,
            KeyId.KEY_3,
            KeyId.KEY_4,
        ]

        # Base colors for the 5 key zones (left → right gradient)
        self.key_base_colors = [
            (255, 170, 170),  # soft pink
            (255, 220, 170),  # peach
            (200, 245, 200),  # mint
            (170, 210, 255),  # light blue
            (225, 185, 255),  # lavender
        ]

    # ---------------- public API ----------------

    def reset(self, now: float) -> None:
        """
        Called when entering this mode. Resets the start time for animations.
        """
        self.start_time = now

    def handle_events(self, events: List[InputEvent]) -> None:
        """
        Menu mode currently ignores note events.
        You could add easter-egg input handling here in the future.
        """
        return

    def update(self, now: float) -> None:
        """
        Called once per frame.

        Renders:
            - Pi-ANO text at the top
            - Shimmering 5-key gradient across the panel
        """
        if self.start_time is None:
            self.start_time = now

        t = now - self.start_time

        # 1) Clear background
        self.led.clear_all()

        # 2) Draw "Pi-ANO" text (near the top)
        self._draw_text_pi_ano(y_offset=2)

        # 3) Draw shimmering 5-key gradient
        self._draw_shimmer_keys(t)

        # 4) Push to hardware
        self.led.show()

    # ---------------- helpers ----------------

    def _set(self, x: int, y: int, color) -> None:
        """
        Map logical (x, y) to physical LED coordinates with a flipped y-axis.
        Logical (0,0) is top-left; physical uses (0, height-1) as bottom-left.
        """
        if not (0 <= x < self.led.width and 0 <= y < self.led.height):
            return
        flipped_y = self.led.height - 1 - y
        self.led.set_xy(x, flipped_y, color)

    def _draw_text_pi_ano(self, y_offset: int) -> None:
        """
        Draw "Pi-ANO" using a 3x5 font, horizontal centering,
        and per-letter colors.
        """
        text = "PI-ANO"
        char_w = 3
        char_h = 5
        spacing = 1

        total_width = len(text) * char_w + (len(text) - 1) * spacing
        left_x = (self.led.width - total_width) // 2

        for i, ch in enumerate(text):
            glyph = self._font().get(ch.upper())
            if glyph is None:
                continue

            x_offset = left_x + i * (char_w + spacing)
            if x_offset >= self.led.width:
                break

            color = (
                self.text_colors[i]
                if i < len(self.text_colors)
                else (255, 255, 255)
            )

            for gy in range(char_h):
                if y_offset + gy >= self.led.height:
                    continue
                row = glyph[gy]
                for gx in range(char_w):
                    if x_offset + gx >= self.led.width:
                        continue
                    if row[gx] == "#":
                        self._set(x_offset + gx, y_offset + gy, color)

    def _draw_shimmer_keys(self, t: float) -> None:
        """
        Render the 5 key zones as a moving rainbow with breathing brightness.

        For each key:
            - Hue cycles through the rainbow over time (HSV -> RGB).
            - Neighboring keys have a phase offset so the rainbow flows.
            - Brightness also breathes (like a soft pulse).
        """
        num_keys = len(self.menu_keys)

        # How fast the rainbow hue moves over time
        hue_speed = 0.1   # smaller = slower rainbow
        # How fast the brightness breathes
        breathe_speed = 2.0

        for idx, key in enumerate(self.menu_keys):
            # Base hue offset per key (spread keys across the rainbow)
            base_hue_offset = idx / max(1, num_keys)

            # Time-based hue shift
            hue = (base_hue_offset + t * hue_speed) % 1.0

            # Breathing brightness: value in [0.4, 1.0]
            breathe_phase = t * breathe_speed + idx * 0.7
            wave = 0.5 + 0.5 * math.sin(breathe_phase)
            value = 0.4 + 0.6 * wave  # V in HSV

            # Full saturation for vivid colors
            sat = 1.0

            # HSV → RGB (each in [0, 1])
            r_f, g_f, b_f = colorsys.hsv_to_rgb(hue, sat, value)

            # Convert to 0–255
            r = int(r_f * 255)
            g = int(g_f * 255)
            b = int(b_f * 255)

            # Paint this key; brightness baked into the color
            self.led.fill_key(key, (r, g, b), brightness=1.0)

    # Lazily build the small 3x5 font
    def _font(self):
        return {
            "P": [
                "###",
                "#.#",
                "###",
                "#..",
                "#..",
            ],
            "I": [
                "###",
                ".#.",
                ".#.",
                ".#.",
                "###",
            ],
            "A": [
                ".#.",
                "#.#",
                "###",
                "#.#",
                "#.#",
            ],
            "N": [
                "#.#",
                "##.",
                "#.#",
                "#.#",
                "#.#",
            ],
            "O": [
                "###",
                "#.#",
                "#.#",
                "#.#",
                "###",
            ],
            "-": [
                "...",
                "...",
                "###",
                "...",
                "...",
            ],
        }

