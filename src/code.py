# code.py — Pico2 HUB75 UI for Pi-ano rhythm/menu/piano/song
#
# Protocol (Pi → Pico via USB serial):
#   MODE:menu
#   MODE:piano
#   MODE:rhythm
#   MODE:song
#
#   RHYTHM:COUNTDOWN          # start 5→1 countdown (Pico prints RHYTHM:COUNTDOWN_DONE)
#   RHYTHM:INGAME             # show RYTHM.bmp during game
#   RHYTHM:RESULT:x/y         # (optional) show final score x/y
#   RHYTHM:LEVEL:easy         # remember selected level (easy/medium/hard), show HARD/MEDIUM/EASY bmp
#
#   # Post-game flow (Pi in charge of timing):
#   RHYTHM:CHALLENGE_FAIL       # scroll "CHALLENGE FAIL"
#   RHYTHM:CHALLENGE_SUCCESS    # scroll "NEW RECORD!"
#   RHYTHM:USER_SCORE_LABEL     # scroll "YOUR SCORE"
#   RHYTHM:USER_SCORE:x/y       # show user's score in center (big)
#   RHYTHM:BEST_SCORE_LABEL     # scroll "BEST SCORE"
#   RHYTHM:BEST_SCORE:x/y       # show best score in center (smaller)
#   RHYTHM:BACK_TO_TITLE        # show RYTHM.bmp, then go back to SELECT cycle

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
supervisor.runtime.autoreload = False
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

COUNTDOWN_TOTAL_SEC = 5.0
COUNTDOWN_DONE_SENT = False

CURRENT_RHYTHM_LEVEL = None

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

def clear_group():
    while len(main_group):
        main_group.pop()
    gc.collect()

def show_fullscreen_bmp(path):
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

def _make_center_label(text: str, font, color: int):
    lbl = Label(
        font,
        text=text,
        color=color,
        anchor_point=(0.5, 0.5),
    )
    lbl.anchored_position = (WIDTH // 2, HEIGHT // 2)
    return lbl

def show_center_text(text, small=True, color=WHITE):
    clear_group()
    if (not small) and (font_large is not None):
        font = font_large
    else:
        font = font_small or font_large
    if font is None:
        return
    lbl = _make_center_label(text, font, color)
    main_group.append(lbl)

def show_rhythm_level(level: str):
    level_l = level.strip().lower()
    if level_l == "hard":
        path = "/graphics/HARD.bmp"
    elif level_l == "medium":
        path = "/graphics/MEDIUM.bmp"
    else:
        path = "/graphics/EASY.bmp"
    show_fullscreen_bmp(path)

def show_user_score(score_text: str):
    """
    當局分數：大字顯示（可以是 'x/y'）
    """
    text = score_text.strip()
    clear_group()
    font = font_small
    if font is None:
        return
    lbl = _make_center_label(text, font, GREEN)
    main_group.append(lbl)

def show_best_score(score_text: str):
    """
    歷史最高分：固定用小字顯示（一定比 user score 小）
    """
    text = score_text.strip()
    clear_group()
    font = font_small or font_large
    if font is None:
        return
    lbl = _make_center_label(text, font, RED)
    main_group.append(lbl)

# ---------------------------------------------------------------------------
# MENU mode: PRESS / BUTTON / TO / CHANGE / MODE 循環播放
# ---------------------------------------------------------------------------

MENU_BMP_PATHS = [
    "/graphics/PRESS.bmp",
    "/graphics/BUTTON.bmp",
    "/graphics/TO.bmp",
    "/graphics/CHANGE.bmp",
    "/graphics/MODE.bmp",
]
MENU_FRAME_DURATION = 0.6

_menu_index = 0
_menu_last_switch = 0.0

def enter_menu_mode():
    global _menu_index, _menu_last_switch
    _menu_index = 0
    _menu_last_switch = time.monotonic() - MENU_FRAME_DURATION
    show_fullscreen_bmp(MENU_BMP_PATHS[_menu_index])

def update_menu_mode(now: float):
    global _menu_index, _menu_last_switch
    if now - _menu_last_switch >= MENU_FRAME_DURATION:
        _menu_last_switch = now
        _menu_index = (_menu_index + 1) % len(MENU_BMP_PATHS)
        show_fullscreen_bmp(MENU_BMP_PATHS[_menu_index])

# ---------------------------------------------------------------------------
# RHYTHM SELECT: BMP 循環
# ---------------------------------------------------------------------------

RHYTHM_SELECT_BMPS = [
    "/graphics/select.bmp",
    "/graphics/Mode_orange.bmp",
    "/graphics/EASY.bmp",
    "/graphics/MEDIUM.bmp",
    "/graphics/HARD.bmp",
]
RHYTHM_SELECT_FRAME_DURATION = 0.6

_rhythm_select_index = 0
_rhythm_select_last_switch = 0.0

def enter_rhythm_select_mode():
    global _rhythm_select_index, _rhythm_select_last_switch
    _rhythm_select_index = 0
    _rhythm_select_last_switch = time.monotonic()
    show_fullscreen_bmp(RHYTHM_SELECT_BMPS[_rhythm_select_index])

def update_rhythm_select_mode(now: float):
    global _rhythm_select_index, _rhythm_select_last_switch
    if now - _rhythm_select_last_switch >= RHYTHM_SELECT_FRAME_DURATION:
        _rhythm_select_last_switch = now
        _rhythm_select_index = (_rhythm_select_index + 1) % len(RHYTHM_SELECT_BMPS)
        show_fullscreen_bmp(RHYTHM_SELECT_BMPS[_rhythm_select_index])

# ---------------------------------------------------------------------------
# Scroll message helper (跑馬燈)
# ---------------------------------------------------------------------------

SCROLL_SPEED = 20.0  # pixels / sec

_scroll_group = None
_scroll_width = 0

def enter_scroll_message(text: str, color: int):
    global _scroll_group, _scroll_width

    clear_group()
    _scroll_group = displayio.Group()
    main_group.append(_scroll_group)

    font = font_small or font_large
    if font is None:
        return

    lbl = Label(
        font,
        text=text,
        color=color,
        anchor_point=(0.0, 0.5),
    )
    lbl.anchored_position = (0, HEIGHT // 2)
    _scroll_group.append(lbl)

    _, _, bw, _ = lbl.bounding_box
    _scroll_width = bw

def update_scroll_message(now: float):
    global _scroll_group, _scroll_width
    if _scroll_group is None or _scroll_width <= 0:
        return

    t = now - STATE_ENTER_TIME
    if t < 0:
        t = 0

    distance = (t * SCROLL_SPEED) % (_scroll_width + WIDTH)
    _scroll_group.x = int(WIDTH - distance)

# ---------------------------------------------------------------------------
# Serial I/O
# ---------------------------------------------------------------------------

def read_serial_line():
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
    name = mode_name.strip().lower()

    if name == "menu":
        set_state("MENU")
        enter_menu_mode()

    elif name == "piano":
        set_state("PIANO")
        show_fullscreen_bmp("/graphics/AIR.bmp")

    elif name == "rhythm":
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
    global CURRENT_RHYTHM_LEVEL

    line = read_serial_line()
    if not line:
        return

    up = line.upper()

    # ───────── MODE:xxx ─────────
    if up.startswith("MODE:"):
        parts = line.split(":", 1)
        if len(parts) == 2:
            handle_mode_command(parts[1])
        return

    # ───────── RHYTHM core signals ─────────
    if up.startswith("RHYTHM:COUNTDOWN"):
        set_state("RHYTHM_COUNTDOWN")
        clear_group()
        return

    if up.startswith("RHYTHM:INGAME"):
        set_state("RHYTHM_INGAME")
        show_fullscreen_bmp("/graphics/RYTHM.bmp")
        return

    if up.startswith("RHYTHM:RESULT:"):
        parts = line.split(":", 2)
        if len(parts) == 3:
            score_text = parts[2]
            set_state("RHYTHM_RESULT")
            show_user_score(score_text)
        return

    if up.startswith("RHYTHM:LEVEL:"):
        parts = line.split(":", 2)
        if len(parts) == 3:
            level = parts[2].strip()
            CURRENT_RHYTHM_LEVEL = level
            show_rhythm_level(level)
        return

    # ───────── Post-game 第 1 段：FAIL / SUCCESS 跑馬燈 ─────────
    if up.startswith("RHYTHM:CHALLENGE_FAIL"):
        set_state("RHYTHM_FAIL_SCROLL")
        enter_scroll_message("CHALLENGE FAIL", RED)
        return

    if up.startswith("RHYTHM:CHALLENGE_SUCCESS"):
        set_state("RHYTHM_SUCCESS_SCROLL")
        enter_scroll_message("NEW RECORD!", MATCHA)
        return

    # ───────── Post-game 第 2 段：YOUR SCORE 跑馬燈 + 分數 ─────────
    if up.startswith("RHYTHM:USER_SCORE_LABEL"):
        set_state("RHYTHM_USER_LABEL_SCROLL")
        enter_scroll_message("YOUR SCORE", WHITE)
        return

    if up.startswith("RHYTHM:USER_SCORE:"):
        parts = line.split(":", 2)
        if len(parts) == 3:
            score_text = parts[2].strip()
            set_state("RHYTHM_SHOW_USER_SCORE")
            show_user_score(score_text)
        return

    # ───────── Post-game 第 3 段：BEST SCORE 跑馬燈 + 分數 ─────────
    if up.startswith("RHYTHM:BEST_SCORE_LABEL"):
        set_state("RHYTHM_BEST_LABEL_SCROLL")
        enter_scroll_message("BEST SCORE", RED)
        return

    if up.startswith("RHYTHM:BEST_SCORE:"):
        parts = line.split(":", 2)
        if len(parts) == 3:
            score_text = parts[2].strip()
            set_state("RHYTHM_SHOW_BEST_SCORE")
            show_best_score(score_text)
        return

    # ───────── 回到 title ─────────
    if up.startswith("RHYTHM:BACK_TO_TITLE"):
        set_state("RHYTHM_TITLE")
        show_fullscreen_bmp("/graphics/RYTHM.bmp")
        return

    # 若上面都沒吃到，就會落到這裡
    print("Unknown command:", line)

# ---------------------------------------------------------------------------
# State machine update
# ---------------------------------------------------------------------------

def update_state(now: float):
    global COUNTDOWN_DONE_SENT

    # MENU
    if STATE == "MENU":
        update_menu_mode(now)
        return

    # RHYTHM_TITLE: 顯示 3 秒 → SELECT
    if STATE == "RHYTHM_TITLE":
        if now - STATE_ENTER_TIME >= 3.0:
            set_state("RHYTHM_SELECT")
            enter_rhythm_select_mode()
        return

    # RHYTHM_SELECT
    if STATE == "RHYTHM_SELECT":
        update_rhythm_select_mode(now)
        return

    # 倒數 5→1
    if STATE == "RHYTHM_COUNTDOWN":
        dt = now - STATE_ENTER_TIME
        if dt < 0:
            dt = 0.0

        if dt < COUNTDOWN_TOTAL_SEC:
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
                lbl = _make_center_label(digit, font, WHITE)
                main_group.append(lbl)
        else:
            if not COUNTDOWN_DONE_SENT:
                print("RHYTHM:COUNTDOWN_DONE")
                COUNTDOWN_DONE_SENT = True
        return

    # 所有跑馬燈狀態
    if STATE in (
        "RHYTHM_FAIL_SCROLL",
        "RHYTHM_SUCCESS_SCROLL",
        "RHYTHM_USER_LABEL_SCROLL",
        "RHYTHM_BEST_LABEL_SCROLL",
    ):
        update_scroll_message(now)
        return

    # 其他狀態：靜態畫面，不用更新
    return

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

print("*** Pico2 HUB75 mode/rhythm UI ready ***")

while True:
    now = time.monotonic()
    process_serial_command()
    update_state(now)
    time.sleep(0.02)
