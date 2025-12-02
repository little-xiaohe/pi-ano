# SPDX-FileCopyrightText: 2021 Kattni Rembor
# SPDX-License-Identifier: MIT

"""
code.py — USB-controlled NeoPixel test on Raspberry Pi Pico (CircuitPython)

Protocol (from Raspberry Pi over USB serial):
- Send lines ending with '\n':
    - "PING\n"      -> Pico replies "PONG"
    - "LED_TEST\n"  -> Pico turns all pixels red once, measures local time in ms,
                       replies "DONE <ms>"

This uses USB CDC (sys.stdin / print) instead of UART pins.
"""

import time
import sys
import board
import neopixel

# -----------------------
# NeoPixel Settings
# -----------------------
NUM_PIXELS = 512
PIXEL_PIN = board.GP0        # 建議用 GP2，比 GP0 穩定；如果你接在 GP0 就改成 board.GP0
BRIGHTNESS = 0.3

pixels = neopixel.NeoPixel(
    PIXEL_PIN,
    NUM_PIXELS,
    brightness=BRIGHTNESS,
    auto_write=False,        # 我們自己呼叫 show()
)

print("Pico LED Matrix + USB Control Ready")

# -----------------------
# Helper: set color
# -----------------------
def all_off():
    """Turn off all pixels."""
    pixels.fill((0, 0, 0))
    pixels.show()


def full_on_red():
    """Turn all pixels fully red."""
    pixels.fill((255, 0, 0))
    pixels.show()


def handle_command(cmd):
    """
    Handle a single uppercase command string (no trailing newline).
    Communication is over USB serial (stdin/stdout).
    """
    cmd = cmd.upper()

    if cmd == "PING":
        # Simple connectivity / RTT test
        print("PONG")

    elif cmd == "LED_TEST":
        # Measure local full-strip ON time on Pico side
        t0 = time.monotonic()
        full_on_red()
        t1 = time.monotonic()
        dt_ms = (t1 - t0) * 1000.0

        # Reply in the format: DONE <ms>
        print("DONE {:.3f}".format(dt_ms))

        # Turn LEDs off after reporting
        all_off()

    else:
        # Unknown command
        print("ERR {}".format(cmd))


# -----------------------
# Main Loop (USB CDC)
# -----------------------
# 這裡用 sys.stdin.readline() 從 USB 收一行一行的指令
while True:
    try:
        line = sys.stdin.readline()
    except Exception:
        # 如果 USB 斷線或出錯，稍微休息一下再試
        time.sleep(0.1)
        continue

    if not line:
        # 沒有收到資料，避免 busy-loop
        time.sleep(0.01)
        continue

    line = line.strip()
    if not line:
        continue

    print("Got command:", repr(line))
    handle_command(line)
