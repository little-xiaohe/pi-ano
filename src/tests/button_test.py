import time
import board
import digitalio

button = digitalio.DigitalInOut(board.D15)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP   # 使用內建上拉電阻

print("按下按鈕試試看 (Ctrl+C 結束)")

while True:
    if not button.value:   # LOW 代表按下
        print("Button pressed!")
        print("")
    else:
        # print("Button released")
        print("")

    time.sleep(0.1)
#25 24 18 15 14