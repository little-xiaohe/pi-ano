# code.py — Pico2 HUB75 UI for Pi-ano rhythm/menu/piano/song
#
# Protocol (Pi → Pico via USB serial):
#
#   MODE:menu
#   MODE:piano
#   MODE:rhythm
#   MODE:song
#
#   RHYTHM:COUNTDOWN          # start 5→1 countdown (Pico prints RHYTHM:COUNTDOWN_DONE, then holds level bmp)
#   RHYTHM:INGAME             # keep showing selected level during gameplay (fallback to RYTHM.bmp if none)
#   RHYTHM:RESULT:x/y         # show final score x/y (text)
#   RHYTHM:LEVEL:easy|medium|hard
#       - NEW BEHAVIOR:
#         When Pi sends RHYTHM:LEVEL:*, Pico immediately starts countdown.
#         When countdown finishes:
#           1) Pico prints "RHYTHM:COUNTDOWN_DONE"
#           2) Pico shows EASY/MEDIUM/HARD.bmp and holds it.
#
# Post-game flow (Pi controls timing):
#   RHYTHM:CHALLENGE_FAIL     # marquee "CHALLENGE FAIL"
#   RHYTHM:CHALLENGE_SUCCESS  # marquee "NEW RECORD!"
#   RHYTHM:USER_SCORE_LABEL   # marquee "YOUR SCORE"
#   RHYTHM:USER_SCORE:x/y     # static score (hold)
#   RHYTHM:BEST_SCORE_LABEL   # marquee "BEST SCORE"
#   RHYTHM:BEST_SCORE:x/y     # static best (hold)  -> Pico will print RHYTHM:BEST_SCORE_DONE after hold ends
#   RHYTHM:BACK_TO_TITLE      # show RYTHM.bmp for 3s, then attract loop until LEVEL arrives
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
# Disable auto reload (CircuitPython hot-reload)
# ---------------------------------------------------------------------------
supervisor.runtime.autoreload = False

# ---------------------------------------------------------------------------
# Display setup (HUB75 32x16)
# ---------------------------------------------------------------------------
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

# Countdown (non-blocking)
COUNTDOWN_TOTAL_SEC = 5.0
COUNTDOWN_DONE_SENT = False

# Rhythm selection
CURRENT_RHYTHM_LEVEL = None  # "easy" | "medium" | "hard" | None

RHYTHM_TITLE_HOLD_SEC = 3.0
RHYTHM_ATTRACT_PATHS = [
    "/graphics/select.bmp",
    "/graphics/Mode_orange.bmp",
    "/graphics/EASY.bmp",
    "/graphics/MEDIUM.bmp",
    "/graphics/HARD.bmp",
]
RHYTHM_ATTRACT_FRAME_SEC = 1.0
_rhythm_attract_index = 0
_rhythm_attract_last_switch = 0.0

LEVEL_TO_BMP = {
    "easy": "/graphics/EASY.bmp",
    "medium": "/graphics/MEDIUM.bmp",
    "hard": "/graphics/HARD.bmp",
}

# ---------------------------------------------------------------------------
# Marquee (scrolling text) + timed lock + FIFO buffering
# ---------------------------------------------------------------------------
_SCROLL_LABEL = None
_SCROLL_X = 0.0
_SCROLL_LAST_T = 0.0

SCROLL_SPEED_PX = 16.0   # pixels/sec
SCROLL_GAP_PX = 12       # spacing between repeats

MARQUEE_TOTAL_SEC = 6.0      # show marquee for at least this many seconds
MARQUEE_LOCK_UNTIL = 0.0     # while locked, non-urgent commands are queued

# ---------------------------------------------------------------------------
# Static score hold lock + BEST_SCORE_DONE ACK
# Split per-score hold time so ONLY BEST is 2 seconds
# ---------------------------------------------------------------------------
USER_SCORE_HOLD_SEC = 5.0
BEST_SCORE_HOLD_SEC = 2.0
RESULT_HOLD_SEC     = 3.0

SCORE_LOCK_UNTIL = 0.0

# Track which score we are showing so we can ACK only after BEST score finishes holding
LAST_SCORE_KIND = None        # None | "RESULT" | "USER" | "BEST"
BEST_SCORE_DONE_SENT = False  # True once we printed RHYTHM:BEST_SCORE_DONE for the latest BEST score

# ---------------------------------------------------------------------------
# FIFO queue for buffered commands (fixes "marquee disappears")
# ---------------------------------------------------------------------------
PENDING_QUEUE = []
PENDING_MAX = 32  # prevent unbounded growth if Pi spams

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
def set_state(new_state: str):
    """Transition to a new UI state."""
    global STATE, STATE_ENTER_TIME, COUNTDOWN_DONE_SENT
    if STATE == new_state and new_state != "RHYTHM_SCROLL":
        return
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

_black_tg = None

def show_black_screen():
    """Force the panel to full black."""
    global _black_tg
    clear_group()
    if _black_tg is None:
        bmp = displayio.Bitmap(WIDTH, HEIGHT, 1)
        pal = displayio.Palette(1)
        pal[0] = 0x000000
        _black_tg = displayio.TileGrid(bmp, pixel_shader=pal)
    main_group.append(_black_tg)

def show_fullscreen_bmp(path: str):
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
    """Create a centered Label."""
    lbl = Label(font, text=text, color=color, anchor_point=(0.5, 0.5))
    lbl.anchored_position = (WIDTH // 2, HEIGHT // 2)
    return lbl

def show_center_text(text: str, font, color: int):
    """Show centered text."""
    clear_group()
    if font is None:
        return
    main_group.append(_make_center_label(text, font, color))

def show_score_text(text: str, color=WHITE):
    """Show centered score text (static)."""
    font = font_small or font_large
    show_center_text(text, font, color)

def show_rhythm_level_hold():
    """Show selected difficulty BMP and hold it."""
    if CURRENT_RHYTHM_LEVEL in LEVEL_TO_BMP:
        show_fullscreen_bmp(LEVEL_TO_BMP[CURRENT_RHYTHM_LEVEL])
    else:
        show_fullscreen_bmp("/graphics/RYTHM.bmp")

def start_marquee(text: str, color: int, font=None):
    """
    Start a left-scrolling marquee (non-blocking).
    Uses anchor-based vertical centering.
    """
    global _SCROLL_LABEL, _SCROLL_X, _SCROLL_LAST_T
    global MARQUEE_LOCK_UNTIL

    clear_group()

    if font is None:
        font = font_small or font_large
    if font is None:
        return

    padded = f"   {text}   "
    lbl = Label(font, text=padded, color=color)

    # Anchor-based vertical centering
    lbl.anchor_point = (0.0, 0.5)
    lbl.anchored_position = (WIDTH, HEIGHT // 2)

    _SCROLL_LABEL = lbl
    _SCROLL_X = float(WIDTH)
    _SCROLL_LAST_T = time.monotonic()

    main_group.append(lbl)

    # Enter marquee state
    global STATE, STATE_ENTER_TIME
    STATE = "RHYTHM_SCROLL"
    STATE_ENTER_TIME = time.monotonic()
    print("STATE ->", STATE)

    # Lock the screen for a fixed duration
    MARQUEE_LOCK_UNTIL = time.monotonic() + MARQUEE_TOTAL_SEC

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

def enter_menu_mode(now: float):
    """Enter MENU mode and show the first frame."""
    global _menu_index, _menu_last_switch
    set_state("MENU")
    _menu_index = 0
    _menu_last_switch = now
    show_fullscreen_bmp(MENU_BMP_PATHS[_menu_index])

def update_menu_mode(now: float):
    """Update menu BMP slideshow."""
    global _menu_index, _menu_last_switch
    if now - _menu_last_switch >= MENU_FRAME_DURATION:
        _menu_last_switch = now
        _menu_index = (_menu_index + 1) % len(MENU_BMP_PATHS)
        show_fullscreen_bmp(MENU_BMP_PATHS[_menu_index])

# ---------------------------------------------------------------------------
# Rhythm UI: title → attract loop
# ---------------------------------------------------------------------------
def enter_rhythm_title():
    """Show RYTHM.bmp for a while, then auto-enter attract loop."""
    global _rhythm_attract_index, _rhythm_attract_last_switch, CURRENT_RHYTHM_LEVEL
    CURRENT_RHYTHM_LEVEL = None
    _rhythm_attract_index = 0
    _rhythm_attract_last_switch = 0.0
    set_state("RHYTHM_TITLE")
    show_fullscreen_bmp("/graphics/RYTHM.bmp")

def enter_rhythm_attract(now: float):
    """Enter rhythm attract loop."""
    global _rhythm_attract_index, _rhythm_attract_last_switch
    _rhythm_attract_index = 0
    _rhythm_attract_last_switch = now
    set_state("RHYTHM_ATTRACT")
    show_fullscreen_bmp(RHYTHM_ATTRACT_PATHS[_rhythm_attract_index])

def update_rhythm_attract(now: float):
    """Update rhythm attract loop frames."""
    global _rhythm_attract_index, _rhythm_attract_last_switch
    if now - _rhythm_attract_last_switch >= RHYTHM_ATTRACT_FRAME_SEC:
        _rhythm_attract_last_switch = now
        _rhythm_attract_index = (_rhythm_attract_index + 1) % len(RHYTHM_ATTRACT_PATHS)
        show_fullscreen_bmp(RHYTHM_ATTRACT_PATHS[_rhythm_attract_index])

# ---------------------------------------------------------------------------
# Serial I/O
# ---------------------------------------------------------------------------
def read_serial_line():
    """Read one line from USB serial (non-blocking)."""
    if supervisor.runtime.serial_bytes_available == 0:
        return None
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        line = line.strip("\n")
        if line:
            print("RX:", line)
        return line
    except Exception as e:
        print("Serial read error:", e)
        return None

# ---------------------------------------------------------------------------
# Command parsing helpers
# ---------------------------------------------------------------------------
def _set_level_from_line(line: str):
    """Parse RHYTHM:LEVEL:* and update CURRENT_RHYTHM_LEVEL."""
    global CURRENT_RHYTHM_LEVEL
    try:
        lvl = line.split(":", 2)[2].strip().lower()
    except Exception:
        lvl = None
    if lvl in ("easy", "medium", "hard"):
        CURRENT_RHYTHM_LEVEL = lvl
    else:
        CURRENT_RHYTHM_LEVEL = None

def _cmd_is_urgent(cmd_upper: str) -> bool:
    """
    Commands that must be allowed to override screen immediately.
    These can break marquee/score locks.
    """
    if cmd_upper == "LED:CLEAR":
        return True
    if cmd_upper.startswith("MODE:"):
        return True
    if cmd_upper.startswith("RHYTHM:LEVEL:"):
        return True
    if cmd_upper.startswith("RHYTHM:COUNTDOWN"):
        return True
    return False

def _enqueue(line: str):
    """Push a line into FIFO queue, with a max cap."""
    global PENDING_QUEUE
    if len(PENDING_QUEUE) >= PENDING_MAX:
        # Drop oldest to keep newest commands
        PENDING_QUEUE = PENDING_QUEUE[-(PENDING_MAX - 1):]
    PENDING_QUEUE.append(line)

def _handle_line(line: str):
    """Handle one sanitized command line."""
    global SCORE_LOCK_UNTIL, LAST_SCORE_KIND, BEST_SCORE_DONE_SENT

    up = line.upper()

    # LED:CLEAR — highest priority
    if up == "LED:CLEAR":
        set_state("LED_OFF")
        show_black_screen()
        return

    # MODE:<name>
    if up.startswith("MODE:"):
        name = line.split(":", 1)[1].strip().lower()
        now = time.monotonic()
        if name == "menu":
            enter_menu_mode(now)
        elif name == "piano":
            set_state("PIANO")
            show_fullscreen_bmp("/graphics/AIR.bmp")
        elif name == "rhythm":
            enter_rhythm_title()
        elif name == "song":
            set_state("SONG")
            show_fullscreen_bmp("/graphics/SONG.bmp")
        else:
            set_state("UNKNOWN")
            show_center_text(name[:4].upper(), font_small, WHITE)
        return

    # RHYTHM:BACK_TO_TITLE
    if up == "RHYTHM:BACK_TO_TITLE":
        enter_rhythm_title()
        return

    # RHYTHM:LEVEL:* starts countdown immediately
    if up.startswith("RHYTHM:LEVEL:"):
        _set_level_from_line(line)
        set_state("RHYTHM_COUNTDOWN")
        clear_group()
        return

    # RHYTHM:COUNTDOWN (still supported)
    if up.startswith("RHYTHM:COUNTDOWN"):
        set_state("RHYTHM_COUNTDOWN")
        clear_group()
        return

    # RHYTHM:INGAME
    if up.startswith("RHYTHM:INGAME"):
        set_state("RHYTHM_INGAME")
        show_rhythm_level_hold()
        return

    # RHYTHM:RESULT:x/y (static)
    if up.startswith("RHYTHM:RESULT:"):
        set_state("RHYTHM_POST")
        text = line.split(":", 2)[2].strip()
        show_score_text(text, WHITE)
        SCORE_LOCK_UNTIL = time.monotonic() + RESULT_HOLD_SEC
        LAST_SCORE_KIND = "RESULT"
        BEST_SCORE_DONE_SENT = False
        return

    # Post-game flow (marquee)
    if up == "RHYTHM:CHALLENGE_FAIL":
        start_marquee("CHALLENGE FAIL", RED)
        return

    if up == "RHYTHM:CHALLENGE_SUCCESS":
        start_marquee("NEW RECORD!", MATCHA)
        return

    if up == "RHYTHM:USER_SCORE_LABEL":
        start_marquee("YOUR SCORE", WHITE)
        return

    # Static user score (hold)
    if up.startswith("RHYTHM:USER_SCORE:"):
        set_state("RHYTHM_POST")
        text = line.split(":", 2)[2].strip()
        show_score_text(text, WHITE)
        SCORE_LOCK_UNTIL = time.monotonic() + USER_SCORE_HOLD_SEC
        LAST_SCORE_KIND = "USER"
        BEST_SCORE_DONE_SENT = False
        return

    if up == "RHYTHM:BEST_SCORE_LABEL":
        start_marquee("BEST SCORE", GREEN)
        return

    # Static best score (hold) -> later emit RHYTHM:BEST_SCORE_DONE
    if up.startswith("RHYTHM:BEST_SCORE:"):
        set_state("RHYTHM_POST")
        text = line.split(":", 2)[2].strip()
        show_score_text(text, GREEN)
        SCORE_LOCK_UNTIL = time.monotonic() + BEST_SCORE_HOLD_SEC
        LAST_SCORE_KIND = "BEST"
        BEST_SCORE_DONE_SENT = False
        return

    # Unknown command
    set_state("UNKNOWN_CMD")
    show_center_text(up[:4], font_small or font_large, WHITE)

# ---------------------------------------------------------------------------
# Command processing (with lock + FIFO queue)
# ---------------------------------------------------------------------------
def process_serial_command():
    """
    Read exactly one line and either handle it now, or enqueue it if we are in a lock window.
    """
    line = read_serial_line()
    if not line:
        return

    # Strong sanitize: keep only visible ASCII
    line = line.replace("\x00", "")
    line = line.replace("\r", "")
    line = "".join(ch for ch in line if 32 <= ord(ch) <= 126).strip()
    if not line:
        return

    up = line.upper()
    now = time.monotonic()

    # If marquee is locked, enqueue non-urgent commands instead of dropping them
    if STATE == "RHYTHM_SCROLL" and now < MARQUEE_LOCK_UNTIL:
        if not _cmd_is_urgent(up):
            _enqueue(line)
            return

    # If static score is locked, enqueue non-urgent commands as well
    if STATE == "RHYTHM_POST" and now < SCORE_LOCK_UNTIL:
        if not _cmd_is_urgent(up):
            _enqueue(line)
            return

    # Otherwise handle immediately
    _handle_line(line)

# ---------------------------------------------------------------------------
# State update
# ---------------------------------------------------------------------------
def update_state(now: float):
    """
    Update animations and timed transitions.
    Also replays buffered commands once lock windows are over.
    """
    global COUNTDOWN_DONE_SENT
    global _SCROLL_X, _SCROLL_LAST_T
    global PENDING_QUEUE
    global LAST_SCORE_KIND, BEST_SCORE_DONE_SENT

    # Emit an ACK when BEST score has finished its minimum hold time.
    if (
        STATE == "RHYTHM_POST"
        and LAST_SCORE_KIND == "BEST"
        and (not BEST_SCORE_DONE_SENT)
        and now >= SCORE_LOCK_UNTIL
    ):
        print("RHYTHM:BEST_SCORE_DONE")
        BEST_SCORE_DONE_SENT = True

    # If locks are over, replay queued commands (one per loop to keep UI smooth)
    marquee_locked = (STATE == "RHYTHM_SCROLL" and now < MARQUEE_LOCK_UNTIL)
    score_locked   = (STATE == "RHYTHM_POST" and now < SCORE_LOCK_UNTIL)
    if (not marquee_locked) and (not score_locked) and PENDING_QUEUE:
        line = PENDING_QUEUE.pop(0)
        _handle_line(line)
        # Continue current state's animation too (do not return)

    if STATE == "LED_OFF":
        return

    if STATE == "MENU":
        update_menu_mode(now)
        return

    if STATE == "RHYTHM_TITLE":
        if now - STATE_ENTER_TIME >= RHYTHM_TITLE_HOLD_SEC:
            enter_rhythm_attract(now)
        return

    if STATE == "RHYTHM_ATTRACT":
        update_rhythm_attract(now)
        return

    if STATE == "RHYTHM_SCROLL":
        if _SCROLL_LABEL is None:
            return

        dt = now - _SCROLL_LAST_T
        _SCROLL_LAST_T = now

        _SCROLL_X -= SCROLL_SPEED_PX * dt
        _SCROLL_LABEL.anchored_position = (int(_SCROLL_X), HEIGHT // 2)

        # Loop the marquee continuously
        if _SCROLL_X < -_SCROLL_LABEL.width - SCROLL_GAP_PX:
            _SCROLL_X = float(WIDTH)
            _SCROLL_LABEL.anchored_position = (int(_SCROLL_X), HEIGHT // 2)
        return

    if STATE == "RHYTHM_COUNTDOWN":
        dt = now - STATE_ENTER_TIME
        if dt < COUNTDOWN_TOTAL_SEC:
            digit = str(5 - int(dt))  # 5,4,3,2,1
            clear_group()
            font = font_large or font_small
            if font:
                main_group.append(_make_center_label(digit, font, WHITE))
        else:
            if not COUNTDOWN_DONE_SENT:
                print("RHYTHM:COUNTDOWN_DONE")
                COUNTDOWN_DONE_SENT = True
                time.sleep(0.02)
                set_state("RHYTHM_HOLD_LEVEL")
                show_rhythm_level_hold()
        return

    # RHYTHM_HOLD_LEVEL, RHYTHM_INGAME, RHYTHM_POST: static unless new commands arrive.

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
print("*** Pico2 HUB75 UI ready ***")

while True:
    now = time.monotonic()
    process_serial_command()
    update_state(now)
    time.sleep(0.02)
