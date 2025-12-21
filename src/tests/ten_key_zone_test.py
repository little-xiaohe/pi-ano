"""
test_ten_key_zones.py
----------------------
Visual test for a 16x32 WS2812B matrix on Raspberry Pi 5
using Blinka + CircuitPython neopixel.

Goal:
- Split the 16x32 matrix into 10 vertical "piano key" blocks.
- Each key block has a distinct color so you can see the layout.
- Leftmost column (x=0) and rightmost column (x=31) are reserved.

Assumptions:
- Two 16x16 panels chained horizontally → total 512 pixels.
- Serpentine wiring inside each 16x16 panel:
    row 0: left → right
    row 1: right → left
    row 2: left → right
    ...
- Left panel = pixels[0..255], right panel = pixels[256..511].
- Data pin is on board.D18 (change if needed).
"""

import time
import board
import neopixel

# ===== Matrix & NeoPixel config =====
MATRIX_WIDTH = 32
MATRIX_HEIGHT = 16
NUM_PIXELS = MATRIX_WIDTH * MATRIX_HEIGHT

# PIN = board.D23 # change if your data pin is different
PIN = board.D18 # change if your data pin is different

BRIGHTNESS = 0.03
AUTO_WRITE = False

pixels = neopixel.NeoPixel(
    PIN,
    NUM_PIXELS,
    brightness=BRIGHTNESS,
    auto_write=AUTO_WRITE,
)

# ===== Piano key zones =====
# x = 0 and x = 31 reserved (border)
# 10 keys use x = 1..30, each key is 3 columns wide.

KEY_ZONES = [
    (1, 3),    # key 0
    (4, 6),    # key 1
    (7, 9),    # key 2
    (10, 12),  # key 3
    (13, 15),  # key 4
    (16, 18),  # key 5
    (19, 21),  # key 6
    (22, 24),  # key 7
    (25, 27),  # key 8
    (28, 30),  # key 9
]

# 10 明顯不同的顏色（R, G, B）
KEY_COLORS = [
    (255,   0,   0),  # red
    (255, 165,   0),  # orange
    (255, 255,   0),  # yellow
    (  0, 255,   0),  # green
    (  0, 255, 255),  # cyan
    (  0,   0, 255),  # blue
    (138,  43, 226),  # purple
    (255, 105, 180),  # pink
    (255, 255, 255),  # white
    (160,  82,  45),  # brown
]


# ===== Mapping: (x, y) -> pixel index =====

def xy_to_index(x: int, y: int) -> int:
    """
    Convert (x, y) to linear index for TWO 16x16 panels side-by-side.

    You MAY need to tweak this if your panels are rotated/flipped.
    """
    if not (0 <= x < MATRIX_WIDTH and 0 <= y < MATRIX_HEIGHT):
        raise ValueError(f"Invalid (x, y) = ({x}, {y})")

    # Decide which 16x16 panel
    if x < 16:
        panel = 0
        local_x = x
    else:
        panel = 1
        local_x = x - 16

    # serpentine inside each panel
    if y % 2 == 0:
        # even row: left -> right
        index_in_panel = y * 16 + local_x
    else:
        # odd row: right -> left
        index_in_panel = y * 16 + (15 - local_x)

    return panel * 16 * 16 + index_in_panel


def set_pixel(x: int, y: int, color):
    idx = xy_to_index(x, y)
    pixels[idx] = color


def clear_all():
    pixels.fill((0, 0, 0))
    pixels.show()


def draw_borders(color=(40, 40, 40)):
    """畫左右兩條邊界（x = 0, x = 31）"""
    for y in range(MATRIX_HEIGHT):
        set_pixel(0, y, color)
        set_pixel(MATRIX_WIDTH - 1, y, color)


def draw_key_blocks():
    """把 10 個 key 區塊畫成 10 種顏色"""
    clear_all()

    # optional: 畫左右灰色邊界，方便你肉眼看到範圍
    draw_borders(color=(20, 20, 20))

    for key_index, (x_start, x_end) in enumerate(KEY_ZONES):
        color = KEY_COLORS[key_index]
        for x in range(x_start, x_end + 1):
            for y in range(MATRIX_HEIGHT):
                set_pixel(x, y, color)

    pixels.show()


def main():
    print("Lighting 10 piano key blocks with distinct colors...")
    draw_key_blocks()
    print("If mapping is correct, you should see 10 vertical color bands.")
    print("Press Ctrl+C to turn off and exit.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        clear_all()
        print("Cleared and exiting.")


if __name__ == "__main__":
    main()
