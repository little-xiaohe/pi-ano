import time
import board
import digitalio

led = digitalio.DigitalInOut(board.D18)
led.direction = digitalio.Direction.OUTPUT

print("LED should be ON")

while True:
    led.value = 1
    time.sleep(1)
    led.value = 0
    time.sleep(1)

