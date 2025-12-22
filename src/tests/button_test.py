import time
import board
import digitalio

button = digitalio.DigitalInOut(board.D15)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP   # Use built-in pull-up resistor

print("Press the button to test (Ctrl+C to exit)")

while True:
    if not button.value:   # LOW means pressed
        print("Button pressed!")
        print("")
    else:
        # print("Button released")
        print("")

    time.sleep(0.1)
#25 24 18 15 14