# src/hardware/led/led_matrix.py
"""
led_matrix.py
-------------
Low-level and high-level abstraction for the 16x32 LED matrix.

LOW-LEVEL: coordinate mapping, raw pixel writes.
HIGH-LEVEL: drawing rectangles and piano key blocks.

Key IDs and their zones are defined in hardware.config.keys.
"""

import time
from typing import Tuple

import board
import neopixel

from src.hardware.config.keys import (
    KeyId,
    KEY_ZONES,
    KEY_COLORS,
    ALL_KEYS,
    KEY_COLOR_PALETTES,
)

MATRIX_WIDTH: int = 32
MATRIX_HEIGHT: int = 16
NUM_PIXELS: int = MATRIX_WIDTH * MATRIX_HEIGHT

BRIGHTNESS: float = 0.1
AUTO_WRITE: bool = False


class LedMatrix:
    """
    LOW-LEVEL responsibilities:
        - Initialize NeoPixel strip.
        - Map (x, y) to linear index.
        - Write individual pixels, clear, show.

    HIGH-LEVEL responsibilities:
        - Draw rectangles.
        - Fill/clear piano key blocks (using KeyId and KEY_ZONES).
    """

    def __init__(
        self,
        pin=board.D23,
        num_pixels: int = NUM_PIXELS,
        brightness: float = BRIGHTNESS,
        auto_write: bool = AUTO_WRITE,
    ) -> None:
        self.width = MATRIX_WIDTH
        self.height = MATRIX_HEIGHT

        self._pixels = neopixel.NeoPixel(
            pin,
            num_pixels,
            brightness=brightness,
            auto_write=auto_write,
        )

        # current key color palette (default = KEY_COLORS)
        self.key_colors = dict(KEY_COLORS)

    # ---------------- LOW-LEVEL mapping ----------------

    def _validate_xy(self, x: int, y: int) -> None:
        """
        Raise ValueError if (x, y) is out of bounds.
        """
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError(f"Invalid (x, y) = ({x}, {y})")

    def _xy_to_index(self, x: int, y: int) -> int:
        """
        Map (x, y) coordinates to the linear NeoPixel index.
        Handles two 16x16 panels, with zigzag wiring per row.
        """
        self._validate_xy(x, y)

        if x < 16:
            panel = 0
            local_x = x
        else:
            panel = 1
            local_x = x - 16

        if y % 2 == 0:
            index_in_panel = y * 16 + local_x
        else:
            index_in_panel = y * 16 + (15 - local_x)

        return panel * (16 * 16) + index_in_panel

    # ---------------- LOW-LEVEL pixel operations ----------------

    def set_xy(self, x: int, y: int, color: Tuple[int, int, int]) -> None:
        """
        Set the color of a single pixel at (x, y).
        """
        idx = self._xy_to_index(x, y)
        self._pixels[idx] = color

    def clear_all(self) -> None:
        """
        Set all pixels to black (off).
        """
        self._pixels.fill((0, 0, 0))

    def show(self) -> None:
        """
        Update the physical LED matrix to reflect all changes.
        """
        self._pixels.show()

    # ---------------- HIGH-LEVEL: palette control ----------------

    def set_key_palette(self, palette: dict[KeyId, tuple[int, int, int]]) -> None:
        """
        Replace the current per-key color palette.
        Typically called by modes (piano/song) to randomize key colors.
        """
        self.key_colors = dict(palette)

    # ---------------- HIGH-LEVEL helpers ----------------

    def fill_rect(
        self,
        x_start: int,
        y_start: int,
        x_end: int,
        y_end: int,
        color: Tuple[int, int, int],
    ) -> None:
        """
        Fill a rectangle from (x_start, y_start) to (x_end, y_end) with the given color.
        """
        x_start = max(0, x_start)
        y_start = max(0, y_start)
        x_end = min(self.width - 1, x_end)
        y_end = min(self.height - 1, y_end)

        for x in range(x_start, x_end + 1):
            for y in range(y_start, y_end + 1):
                self.set_xy(x, y, color)

    # ---------------- HIGH-LEVEL: piano keys ----------------

    def _normalize_key(self, key) -> KeyId | None:
        """
        Accept either an int (matching a KeyId value) or a KeyId
        and normalize to KeyId. Returns None if invalid.
        """
        if isinstance(key, KeyId):
            return key
        try:
            return KeyId(int(key))
        except (ValueError, TypeError):
            return None

    def fill_key(
        self,
        key,
        color: Tuple[int, int, int] | None = None,
        brightness: float = 1.0,
    ) -> None:
        """
        Fill one piano key block using the KEY_ZONES definition.
        """
        key_id = self._normalize_key(key)
        if key_id is None or key_id not in KEY_ZONES:
            return

        if color is None:
            color = self.key_colors.get(key_id, (255, 255, 255))

        x_start, x_end = KEY_ZONES[key_id]

        brightness = max(0.0, min(1.0, brightness))
        r, g, b = color
        r = int(r * brightness)
        g = int(g * brightness)
        b = int(b * brightness)

        for x in range(x_start, x_end + 1):
            for y in range(self.height):
                self.set_xy(x, y, (r, g, b))


    def clear_key(self, key) -> None:
        """
        Clear a piano key block (set all pixels in that zone to black).
        """
        key_id = self._normalize_key(key)
        if key_id is None or key_id not in KEY_ZONES:
            return

        x_start, x_end = KEY_ZONES[key_id]
        for x in range(x_start, x_end + 1):
            for y in range(self.height):
                self.set_xy(x, y, (0, 0, 0))

    # ---------------- HIGH-LEVEL: demos ----------------

    def demo_keys_static(self) -> None:
        """
        Show all key zones with their debug colors.
        """
        self.clear_all()
        for key_id in ALL_KEYS:
            x_start, x_end = KEY_ZONES[key_id]
            color = self.key_colors.get(key_id, (255, 255, 255))
            for x in range(x_start, x_end + 1):
                for y in range(self.height):
                    self.set_xy(x, y, color)
        self.show()

    def demo_keys_sweep(self, delay: float = 0.3) -> None:
        """
        Sweep through all keys one by one, using their debug colors.
        Press Ctrl+C to stop.
        """
        try:
            while True:
                for key_id in ALL_KEYS:
                    self.clear_all()
                    base_color = self.key_colors.get(key_id, (255, 255, 255))
                    self.fill_key(key_id, base_color)
                    self.show()
                    time.sleep(delay)
        except KeyboardInterrupt:
            self.clear_all()
            self.show()
