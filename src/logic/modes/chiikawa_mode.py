# src/logic/modes/chiikawa_mode.py

import math
from typing import List

from src.hardware.led.led_matrix import LedMatrix
from src.logic.input_event import InputEvent


class ChiikawaMode:
    """
    Default menu / home screen mode.

    Shows:
      - "Pi-ANO" text (colorful, horizontally centered) near the top.
      - A Pac-Man style mouth at the bottom moving left→right,
        with the mouth opening and closing.

    NOTE:
      This mode uses a flipped-y helper _set() so that logical (0,0)
      is the TOP-LEFT of the panel.
    """

    def __init__(self, led: LedMatrix) -> None:
        self.led = led
        self.start_time: float | None = None

        # Colors
        self.bg_color = (0, 0, 0)

        # colorful letters for "Pi-ANO"
        self.text_colors = [
            (255, 120, 120),  # P
            (255, 200, 120),  # i
            (255, 255, 160),  # -
            (150, 230, 150),  # A
            (140, 180, 255),  # N
            (210, 160, 255),  # O
        ]

        # Pac-Man colors
        self.pac_color = (255, 215, 60)      # yellow-ish
        self.pac_eye_color = (40, 40, 40)    # dark eye

        # 3x5 font for letters (logical top=0)
        self.FONT = {
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

    # ---------------- public API ----------------

    def reset(self, now: float) -> None:
        self.start_time = now

    def handle_events(self, events: List[InputEvent]) -> None:
        # Chiikawa/Pac-Man mode currently ignores note events.
        pass

    def update(self, now: float) -> None:
        if self.start_time is None:
            self.start_time = now

        t = now - self.start_time
        w = self.led.width
        h = self.led.height

        # 1) 填背景
        self.led.clear_all()
        for x in range(w):
            for y in range(h):
                self._set(x, y, self.bg_color)

        # 2) 畫 Pi-ANO（頂端留一點空間，字放在 y=2..6）
        self._draw_text_pi_ano(y_offset=2)

        # 3) Pac-Man 位置 & 嘴巴動畫
        radius = 4.0  # 小小一顆圓
        center_y = h - 4  # 靠下方一點

        # 水平從左往右跑，超出後從左邊再進來
        speed = 5.0  # pixels per second
        loop_len = w + int(2 * radius)
        center_x = int((t * speed) % loop_len) - int(radius)

        # 嘴巴開合：用 sin 畫一個 0~1 的週期，再映射成角度
        # mouth_angle 在 [小張嘴, 大張嘴] 之間變化（弧度）
        phase = 0.5 * (1.0 + math.sin(t * 4.0))  # 4.0 控制開合頻率
        mouth_min = 0.15 * math.pi   # 大約 27 度
        mouth_max = 0.45 * math.pi   # 大約 81 度
        mouth_angle = mouth_min + (mouth_max - mouth_min) * phase

        # 4) 畫 Pac-Man（面向右邊）
        self._draw_pacman(center_x, center_y, radius, mouth_angle)

        self.led.show()

    # ---------------- helpers ----------------

    def _set(self, x: int, y: int, color) -> None:
        """把邏輯座標 (x, y) 映射到實際 LED（翻轉 y）。"""
        if not (0 <= x < self.led.width and 0 <= y < self.led.height):
            return
        flipped_y = self.led.height - 1 - y
        self.led.set_xy(x, flipped_y, color)

    def _draw_text_pi_ano(self, y_offset: int) -> None:
        """
        在指定 y_offset 畫 'Pi-ANO'，3x5 字型＋水平置中＋彩色字。
        """
        text = "PI-ANO"
        char_w = 3
        char_h = 5
        spacing = 1

        total_width = len(text) * char_w + (len(text) - 1) * spacing
        left_x = (self.led.width - total_width) // 2

        for i, ch in enumerate(text):
            glyph = self.FONT.get(ch.upper())
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

    def _draw_pacman(
        self,
        cx: int,
        cy: int,
        radius: float,
        mouth_angle: float,
    ) -> None:
        """
        在中心 (cx, cy) 畫一顆面向右邊的 Pac-Man：
        - 以 radius 當圓半徑
        - mouth_angle 決定嘴巴張開角度（越大越張嘴）
        """
        r2 = radius * radius

        # 掃圓附近的 bounding box 就好
        x_min = int(cx - radius - 1)
        x_max = int(cx + radius + 1)
        y_min = int(cy - radius - 1)
        y_max = int(cy + radius + 1)

        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                dx = x - cx
                dy = y - cy
                dist2 = dx * dx + dy * dy
                if dist2 > r2:
                    continue  # 在圓外

                # angle: 0 在 +x 方向（往右），正負代表上下
                angle = math.atan2(dy, dx)  # [-pi, pi]

                # 嘴巴朝右，把靠近 +x 軸的那一塊挖空
                if -mouth_angle < angle < mouth_angle:
                    continue  # mouth opening

                self._set(x, y, self.pac_color)

        # 小眼睛：在圓的左上方一點
        eye_x = cx - 1
        eye_y = cy - 2
        if 0 <= eye_x < self.led.width and 0 <= eye_y < self.led.height:
            self._set(eye_x, eye_y, self.pac_eye_color)
