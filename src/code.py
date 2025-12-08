# code.py — Pico2 HUB75 UI for Pi-ano rhythm/menu/piano/song
#
# Protocol (Pi → Pico via USB serial):
#   MODE:menu
#   MODE:piano
#   MODE:rhythm
#   MODE:song
#
#   RHYTHM:COUNTDOWN      # start 5→1 countdown (Pico prints RHYTHM:COUNTDOWN_DONE)
#   RHYTHM:INGAME         # show RYTHM.bmp during game
#   RHYTHM:RESULT:x/y     # show final score (e.g. 25/84)

import time
import sys
import gc

import board
import displayio
import framebufferio
import rgbmatrix
import supervisor

from adafruit_bitmap_font import bitmap_font
from adafruit_display_text.label import Label

# ---------------------------------------------------------------------------
# Display setup
# ---------------------------------------------------------------------------

displayio.release_displays()

matrix = rgbmatrix.RGBMatrix(
    width=32,
    height=16,
    bit_depth=6,
    rgb_pins=[
        board.GP2,  # R1
        board.GP3,  # G1
        board.GP6,  # B1
        board.GP7,  # R2
        board.GP8,  # G2
        board.GP9,  # B2
    ],
    addr_pins=[
        board.GP10,  # A
        board.GP16,  # B
        board.GP18,  # C
        # board.GP20,  # D  (not needed for 16px high panel)
    ],
    clock_pin=board.GP11,
    latch_pin=board.GP12,
    output_enable_pin=board.GP13,
    tile=1,
    serpentine=False,
    doublebuffer=True,
)

display = framebufferio.FramebufferDisplay(matrix, auto_refresh=True)

WIDTH = display.width
HEIGHT = display.height

main_group = displayio.Group()
display.root_group = main_group  # root_group 只設一次

# ---------------------------------------------------------------------------
# Fonts / colors
# ---------------------------------------------------------------------------

try:
    font_small = bitmap_font.load_font("/fonts/helvB08.bdf")
except Exception as e:
    print("Error loading /fonts/helvB08.bdf:", e)
    font_small = None

try:
    font_large = bitmap_font.load_font("/fonts/helvB12.bdf")
except Exception as e:
    print("Error loading /fonts/helvB12.bdf:", e)
    font_large = None

WHITE  = 0xFFFFFF
RED    = 0xFF3030
MATCHA = 0x7ACF5A
ORANGE = 0xFFB000
CYAN   = 0x80FFFF
YELLOW = 0xFFF070
PINK   = 0xFF80D0
GREEN  = 0x80FF80

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

STATE = "IDLE"
STATE_ENTER_TIME = time.monotonic()

# 倒數 5→1 用的總秒數
COUNTDOWN_TOTAL_SEC = 5.0
COUNTDOWN_DONE_SENT = False  # 確保 RHYTHM:COUNTDOWN_DONE 只送一次

def set_state(new_state: str):
    global STATE, STATE_ENTER_TIME, COUNTDOWN_DONE_SENT
    STATE = new_state
    STATE_ENTER_TIME = time.monotonic()
    print("STATE ->", STATE)
    if new_state == "RHYTHM_COUNTDOWN":
        COUNTDOWN_DONE_SENT = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def show_rhythm_level(level: str):
    """
    顯示 HARD / MEDIUM / EASY 在 Pico LED 上（置中，顏色依難度）。
    """
    clear_group()

    font = font_large if font_large is not None else font_small
    if font is None:
        return

    level = level.lower()
    if level == "hard":
        text = "HARD"
        color = RED
    elif level == "medium":
        text = "MEDIUM"
        color = ORANGE
    else:
        text = "EASY"
        color = MATCHA

    lbl = Label(font, text=text, color=color, anchor_point=(0.5, 0.5))
    lbl.anchored_position = (WIDTH // 2, HEIGHT // 2)
    main_group.append(lbl)

def clear_group():
    """Remove all children from main_group."""
    while len(main_group):
        main_group.pop()
    gc.collect()

def show_fullscreen_bmp(path):
    """
    Show a BMP file centered on screen.
    Expect 32x16, but center smaller ones as well.
    """
    clear_group()
    try:
        bmp = displayio.OnDiskBitmap(path)
        tg = displayio.TileGrid(
            bmp,
            pixel_shader=bmp.pixel_shader,
            x=(WIDTH - bmp.width) // 2,
            y=(HEIGHT - bmp.height) // 2,
        )
        main_group.append(tg)
    except Exception as e:
        print("BMP error:", path, e)
        show_center_text("ERR", small=True, color=RED)

def show_center_text(text, small=True, color=WHITE):
    """
    Show a single line of text, horizontally & vertically centered.
    使用 anchor_point / anchored_position 避開 bounding_box 的怪 baseline。
    """
    clear_group()

    if (not small) and (font_large is not None):
        font = font_large
    else:
        font = font_small or font_large

    if font is None:
        return

    label = Label(
        font,
        text=text,
        color=color,
        anchor_point=(0.5, 0.5),  # 中心點
    )
    label.anchored_position = (WIDTH // 2, HEIGHT // 2)
    main_group.append(label)

def show_menu_press_button_sequence(delay=0.6):
    """
    For MODE:menu – show PRESS/BUTTON/TO/CHANGE/MODE in sequence.
    """
    paths = [
        "/graphics/PRESS.bmp",
        "/graphics/BUTTON.bmp",
        "/graphics/TO.bmp",
        "/graphics/CHANGE.bmp",
        "/graphics/MODE.bmp",
    ]
    for p in paths:
        show_fullscreen_bmp(p)
        time.sleep(delay)

def show_rhythm_result(score_text):
    """
    RHYTHM:RESULT:x/y – show final score in the center.
    字體大小會自動根據長度調整，垂直與水平都置中。
    """
    text = score_text.strip()
    clear_group()

    font = font_large if font_large is not None else font_small
    if font is None:
        return

    # 先用大字試寬度
    lbl = Label(font, text=text, color=GREEN, anchor_point=(0.5, 0.5))
    _, _, bw, _ = lbl.bounding_box
    if bw > WIDTH and font_small is not None:
        # 太寬就換小字
        font = font_small
        lbl = Label(font, text=text, color=GREEN, anchor_point=(0.5, 0.5))

    lbl.anchored_position = (WIDTH // 2, HEIGHT // 2)
    main_group.append(lbl)


# ---------------------------------------------------------------------------
# SELECT MODE 跑馬燈： "SELECT MODE: HARD MEDIUM EASY"
# ---------------------------------------------------------------------------

SELECT_WORDS = [
    ("SELECT MODE:", WHITE),
    ("HARD", RED),
    ("MEDIUM", ORANGE),
    ("EASY", MATCHA),
]

_select_group = None
_select_scroll_width = 0  # 內容總寬度
SELECT_SCROLL_SPEED = 20.0  # pixels / sec

def enter_rhythm_select_mode():
    """
    進入 RHYTHM_SELECT 狀態時建立跑馬燈：
      "SELECT MODE: HARD MEDIUM EASY"
       - 一行字
       - HARD 紅 / MEDIUM 橘 / EASY 綠
       - 整行垂直置中
       - 從右往左無限滾動
    """
    global _select_group, _select_scroll_width

    clear_group()
    _select_group = displayio.Group()
    main_group.append(_select_group)

    font = font_small or font_large
    if font is None:
        return

    x_cursor = 0
    for text, color in SELECT_WORDS:
        # anchor_point.x = 0 → 用左邊當對齊基準，anchor_point.y = 0.5 → 垂直中心
        lbl = Label(
            font,
            text=text,
            color=color,
            anchor_point=(0.0, 0.5),
        )
        # 讓每個 label 的「左邊＋垂直中心」在 (x_cursor, HEIGHT/2)
        lbl.anchored_position = (x_cursor, HEIGHT // 2)
        _select_group.append(lbl)

        # 用 bounding_box 的寬度往右推
        _, _, bw, _ = lbl.bounding_box
        x_cursor += bw + 4  # 每個字之間空 4px

    _select_scroll_width = x_cursor
    _select_group.x = WIDTH  # 一開始從右邊外面進來


def update_rhythm_select_mode(now: float):
    """
    讓整個 SELECT MODE group 從右往左滾動，超出左邊再從右邊進來。
    """
    global _select_group, _select_scroll_width
    if _select_group is None:
        return
    if _select_scroll_width <= 0:
        return

    t = now - STATE_ENTER_TIME
    if t < 0:
        t = 0

    distance = (t * SELECT_SCROLL_SPEED) % (_select_scroll_width + WIDTH)
    _select_group.x = int(WIDTH - distance)


# ---------------------------------------------------------------------------
# Serial I/O (Pi → Pico)
# ---------------------------------------------------------------------------

def read_serial_line():
    """
    Non-blocking read of one line from USB serial (Pi → Pico).
    Returns None if no data.
    """
    if not supervisor.runtime.serial_connected:
        return None

    if supervisor.runtime.serial_bytes_available == 0:
        return None

    try:
        line = sys.stdin.readline().strip()
        if line:
            print("RX:", line)
        return line
    except Exception as e:
        print("Serial read error:", e)
        return None

# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def handle_mode_command(mode_name):
    """
    MODE:<name> handler.
    """
    name = mode_name.strip().lower()

    if name == "menu":
        set_state("MENU")
        show_menu_press_button_sequence()

    elif name == "piano":
        set_state("PIANO")
        show_fullscreen_bmp("/graphics/AIR.bmp")

    elif name == "rhythm":
        # Step 1: show RYTHM.bmp for 3 seconds, 然後進入 SELECT MODE
        set_state("RHYTHM_TITLE")
        show_fullscreen_bmp("/graphics/RYTHM.bmp")

    elif name == "song":
        set_state("SONG")
        show_fullscreen_bmp("/graphics/SONG.bmp")

    else:
        set_state("UNKNOWN")
        show_center_text(name[:4].upper(), small=True, color=WHITE)

def process_serial_command():
    """
    Parse and handle commands from Pi.
    """
    line = read_serial_line()
    if not line:
        return

    up = line.upper()

    # MODE:xxx
    if up.startswith("MODE:"):
        parts = line.split(":", 1)
        if len(parts) == 2:
            handle_mode_command(parts[1])
        return

    # RHYTHM:COUNTDOWN → 切到 countdown 狀態，由 state machine 畫 5→1
    if up.startswith("RHYTHM:COUNTDOWN"):
        set_state("RHYTHM_COUNTDOWN")
        clear_group()
        return

    # RHYTHM:INGAME → 顯示 RYTHM.bmp
    if up.startswith("RHYTHM:INGAME"):
        set_state("RHYTHM_INGAME")
        show_fullscreen_bmp("/graphics/RYTHM.bmp")
        return

    # RHYTHM:RESULT:x/y
    if up.startswith("RHYTHM:RESULT:"):
        parts = line.split(":", 2)
        if len(parts) == 3:
            score_text = parts[2]
            set_state("RHYTHM_RESULT")
            show_rhythm_result(score_text)
        return

    if up.startswith("RHYTHM:LEVEL:"):
        parts = line.split(":", 2)
        if len(parts) == 3:
            level = parts[2].strip()
            show_rhythm_level(level)
        return
    print("Unknown command:", line)

# ---------------------------------------------------------------------------
# State machine update
# ---------------------------------------------------------------------------

def update_state(now: float):
    """
    Per-frame state updates (non-blocking drawing).
    """
    global COUNTDOWN_DONE_SENT

    # RHYTHM_TITLE: 顯示 RYTHM.bmp 3 秒，然後進入 SELECT MODE 跑馬燈
    if STATE == "RHYTHM_TITLE":
        if now - STATE_ENTER_TIME >= 3.0:
            set_state("RHYTHM_SELECT")
            enter_rhythm_select_mode()
        return

    # RHYTHM_SELECT: 「SELECT MODE: HARD MEDIUM EASY」跑馬燈
    if STATE == "RHYTHM_SELECT":
        update_rhythm_select_mode(now)
        return

    if STATE == "RHYTHM_COUNTDOWN":
        dt = now - STATE_ENTER_TIME
        if dt < 0:
            dt = 0.0

        if dt < COUNTDOWN_TOTAL_SEC:
            # 0~1s -> 5, 1~2s -> 4, 2~3s -> 3, 3~4s -> 2, 4~5s -> 1
            if dt < 1.0:
                digit = "5"
            elif dt < 2.0:
                digit = "4"
            elif dt < 3.0:
                digit = "3"
            elif dt < 4.0:
                digit = "2"
            else:
                digit = "1"

            clear_group()
            font = font_large if font_large is not None else font_small
            if font is not None:
                lbl = Label(
                    font,
                    text=digit,
                    color=WHITE,
                    anchor_point=(0.5, 0.5),
                )
                lbl.anchored_position = (WIDTH // 2, HEIGHT // 2)
                main_group.append(lbl)
        else:
            if not COUNTDOWN_DONE_SENT:
                print("RHYTHM:COUNTDOWN_DONE")
                COUNTDOWN_DONE_SENT = True
        return


    # 其他狀態不需要持續更新畫面（MENU / PIANO / SONG / RHYTHM_INGAME / RHYTHM_RESULT / UNKNOWN）

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

print("*** Pico2 HUB75 mode/rhythm UI ready ***")

while True:
    now = time.monotonic()

    # 1) Handle commands from Pi (may change STATE or start countdown)
    process_serial_command()

    # 2) State-dependent animation / countdown
    update_state(now)

    time.sleep(0.02)
