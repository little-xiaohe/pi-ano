# SPDX-FileCopyrightText: 2021 Kattni Rembor
# SPDX-License-Identifier: MIT

import board
import neopixel
import adafruit_pio_uart
import time

# -----------------------
# NeoPixel Settings
# -----------------------
NUM_PIXELS = 512
pixels = neopixel.NeoPixel(board.GP0, NUM_PIXELS, brightness=0.3, auto_write=False)

# -----------------------
# UART Settings
# -----------------------
uart = adafruit_pio_uart.UART(
    tx=board.GP8,
    rx=board.GP9,
    baudrate=115200,
    timeout=1
)


print("Pico LED Matrix + UART Control Ready")

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


def full_on_random():
    """Fill all pixels with random colors."""
    for i in range(NUM_PIXELS):
        pixels[i] = (
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255)
        )
    pixels.show()

def full_on_random_color():
    """Fill all pixels with the same random color."""
    r = random.randint(0, 255)
    g = random.randint(0, 255)
    b = random.randint(0, 255)
    pixels.fill((r, g, b))
    pixels.show()

def handle_command(cmd: str):
    """
    Handle a single uppercase command string (no trailing newline).
    """
    if cmd == "PING":
        # Simple connectivity / RTT test
        uart.write(b"PONG\n")

    elif cmd == "LED_TEST":
        # Measure local full-strip ON/OFF time on Pico side
        t0 = time.monotonic()
        full_on_red()
        t1 = time.monotonic()
        dt_ms = (t1 - t0) * 1000.0
        # Reply in the format: DONE <ms>
        msg = "DONE {:.3f}\n".format(dt_ms)
        uart.write(msg.encode("utf-8"))
        all_off()


    else:
        # Unknown command; optional error reply
        err = "ERR {}\n".format(cmd)
        uart.write(err.encode("utf-8"))
        
# -----------------------
# Main Loop
# -----------------------
buffer = bytearray()
all_off()

while True:
    b = uart.read(1)
    if b:
        if b == b"\n":  # End of command
            cmd = buffer.decode().strip().upper()
            print("Got command:", cmd)
            handle_command(cmd)
            buffer = bytearray()
        else:
            buffer.extend(b)