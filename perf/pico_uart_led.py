# SPDX-FileCopyrightText: 2021 Kattni Rembor
# SPDX-License-Identifier: MIT

import board
import neopixel
import adafruit_pio_uart

# -----------------------
# NeoPixel Settings
# -----------------------
NUM_PIXELS = 512
pixels = neopixel.NeoPixel(board.GP0, NUM_PIXELS, brightness=0.3, auto_write=True)

# -----------------------
# UART Settings
# -----------------------
uart = adafruit_pio_uart.UART(
    tx=board.GP8,
    rx=board.GP9,
    baudrate=115200,
    timeout=1
)

buffer = bytearray()

print("Pico LED Matrix + UART Control Ready")

# -----------------------
# Helper: set color
# -----------------------
def set_color(r, g, b):
    pixels.fill((r, g, b))

# -----------------------
# Main Loop
# -----------------------
while True:
    b = uart.read(1)
    if b:
        if b == b"\n":  # End of command
            cmd = buffer.decode().strip().upper()
            print("Got command:", cmd)

            if cmd == "RED":
                set_color(255, 0, 0)

            elif cmd == "GREEN":
                set_color(0, 255, 0)

            elif cmd == "BLUE":
                set_color(0, 0, 255)

            elif cmd == "OFF":
                set_color(0, 0, 0)

            buffer = bytearray()

        else:
            buffer.extend(b)
