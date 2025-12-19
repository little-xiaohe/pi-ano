# code.py — Pico2 HUB75 UI for Pi-ano rhythm/menu/piano/song
#
# Protocol (Pi → Pico via USB serial):
#
#   MODE:menu
#   MODE:piano
#   MODE:rhythm
#   MODE:song
#
#   RHYTHM:COUNTDOWN          # start 5→1 countdown (Pico prints RHYTHM:COUNTDOWN_DONE)
#   RHYTHM:INGAME             # show RYTHM.bmp during game
#   RHYTHM:RESULT:x/y         # (optional) show final score x/y
#   RHYTHM:LEVEL:easy         # remember selected level (easy/medium/hard)
#
#   # Post-game flow (Pi controls timing):
#   RHYTHM:CHALLENGE_FAIL
#   RHYTHM:CHALLENGE_SUCCESS
#   RHYTHM:USER_SCORE_LABEL
#   RHYTHM:USER_SCORE:x/y
#   RHYTHM:BEST_SCORE_LABEL
#   RHYTHM:BEST_SCORE:x/y
#   RHYTHM:BACK_TO_TITLE
#
#   LED:CLEAR                 # immediately force the panel to black

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

# Disable autoreload to avoid unexpected resets while running.
supervisor.runtime.autoreload = False
displayio.release_displays()

matrix = rgbmatrix.RGBMatrix(
    width=32,
    height=16,
    bit_depth=6,
    rgb_pins=[
        board.GP2,   # R1
        board.GP3,   # G1
        board.GP6,   # B1
        board.GP7,   # R2
        board.GP8,   # G2
        board.GP9,   # B2
    ],
    addr_pins=[
        board.GP10,  # A
        board.GP16,  # B
        board.GP18,  # C
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
display.root_group = main_group

# ---------------------------------------------------------------------------
# Fonts / colors
# ---------------------------------------------------------------------------

try:
    font_small = bitmap_font.load_font("/fonts/tom-thumb.bdf")
except Exception as e:
    print("Error loading tom-thumb.bdf:", e)
    font_small = None

try:
    font_large = bitmap_font.load_font("/fonts/helvB12.bdf")
except Exception as e:
    print("Error loading helvB12.bdf:", e)
    font_large = None

WHITE  = 0xFFFFFF
RED    = 0xFF3030
MATCHA = 0x7ACF5A
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
    """Transition to a new UI state."""
    global STATE, STATE_ENTER_TIME, COUNTDOWN_DONE_SENT
    STATE = new_state
    STATE_ENTER_TIME = time.monotonic()
    print("STATE ->", STATE)
    if new_state == "RHYTHM_COUNTDOWN":
        COUNTDOWN_DONE_SENT = False

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def clear_group():
    """Remove all elements from the root display group."""
    while len(main_group):
        main_group.pop()
    gc.collect()

# ---------------------------------------------------------------------------
# Hard black screen (more reliable than an empty group on some HUB75 setups)
# ---------------------------------------------------------------------------

_black_tg = None

def show_black_screen():
    """
    Force the panel to full black by showing a dedicated WIDTH×HEIGHT black bitmap.
    This is often more reliable than leaving the group empty.
    """
    global _black_tg

    clear_group()

    if _black_tg is None:
        bmp = displayio.Bitmap(WIDTH, HEIGHT, 1)
        pal = displayio.Palette(1)
        pal[0] = 0x000000
        _black_tg = displayio.TileGrid(bmp, pixel_shader=pal)

    main_group.append(_black_tg)

def show_fullscreen_bmp(path):
    """Show a centered fullscreen BMP image."""
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

def _make_center_label(text: str, font, color: int):
    """Create a centered Label object."""
    lbl = Label(
        font,
        text=text,
        color=color,
        anchor_point=(0.5, 0.5),
    )
    lbl.anchored_position = (WIDTH // 2, HEIGHT // 2)
    return lbl

def show_center_text(text, font, color):
    """Show centered text using the given font."""
    clear_group()
    if font is None:
        return
    lbl = _make_center_label(text, font, color)
    main_group.append(lbl)

# ---------------------------------------------------------------------------
# Menu animation
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
    """Enter MENU mode."""
    global _menu_index, _menu_last_switch
    _menu_index = 0
    _menu_last_switch = time.monotonic() - MENU_FRAME_DURATION
    show_fullscreen_bmp(MENU_BMP_PATHS[_menu_index])

def update_menu_mode(now: float):
    """Advance MENU animation."""
    global _menu_index, _menu_last_switch
    if now - _menu_last_switch >= MENU_FRAME_DURATION:
        _menu_last_switch = now
        _menu_index = (_menu_index + 1) % len(MENU_BMP_PATHS)
        show_fullscreen_bmp(MENU_BMP_PATHS[_menu_index])

# ---------------------------------------------------------------------------
# Serial I/O
# ---------------------------------------------------------------------------

def read_serial_line():
    """
    Read one line from USB serial (non-blocking).

    IMPORTANT:
    Do not gate on supervisor.runtime.serial_connected. In practice it can be False
    even when the host is sending data.
    """
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
# Command processing
# ---------------------------------------------------------------------------

def handle_mode_command(mode_name):
    """Handle MODE:<name> commands."""
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
        show_center_text(name[:4].upper(), font_small, WHITE)

def process_serial_command():
    """Parse and handle commands from the Pi."""
    global CURRENT_RHYTHM_LEVEL

    line = read_serial_line()
    if not line:
        return

    up = line.upper()

    # LED:CLEAR — highest priority
    # Enter LED_OFF so no other state update overwrites the black screen.
    if up == "LED:CLEAR":
        set_state("LED_OFF")
        show_black_screen()
        return

    if up.startswith("MODE:"):
        handle_mode_command(line.split(":", 1)[1])
        return

    if up.startswith("RHYTHM:COUNTDOWN"):
        set_state("RHYTHM_COUNTDOWN")
        clear_group()
        return

    if up.startswith("RHYTHM:INGAME"):
        set_state("RHYTHM_INGAME")
        show_fullscreen_bmp("/graphics/RYTHM.bmp")
        return

# ---------------------------------------------------------------------------
# State update
# ---------------------------------------------------------------------------

def update_state(now: float):
    """Update animations and timed state transitions."""
    global COUNTDOWN_DONE_SENT

    if STATE == "LED_OFF":
        # Keep the panel black until a new command arrives.
        return

    if STATE == "MENU":
        update_menu_mode(now)
        return

    if STATE == "RHYTHM_COUNTDOWN":
        dt = now - STATE_ENTER_TIME
        if dt < COUNTDOWN_TOTAL_SEC:
            digit = str(5 - int(dt))
            clear_group()
            font = font_large or font_small
            if font:
                main_group.append(_make_center_label(digit, font, WHITE))
        else:
            if not COUNTDOWN_DONE_SENT:
                print("RHYTHM:COUNTDOWN_DONE")
                COUNTDOWN_DONE_SENT = True
        return

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

print("*** Pico2 HUB75 UI ready ***")

while True:
    now = time.monotonic()
    process_serial_command()
    update_state(now)
    time.sleep(0.02)
