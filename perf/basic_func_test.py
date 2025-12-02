import time
import board
import neopixel
import sys

NUM_PIXELS = 512
PIN = board.D23   # 或你的 LED DIN 腳位
BRIGHTNESS = 1.0  # 可調整亮度（0.0~1.0）

# 初始化：關掉 auto_write，避免不預期觸發
pixels = neopixel.NeoPixel(
    PIN,
    NUM_PIXELS,
    brightness=BRIGHTNESS,
    auto_write=False,
    # pixel_order=neopixel.RGB
)

# pixels = neopixel.NeoPixel(PIN, NUM_PIXELS, brightness=0.3, auto_write=False)
print(pixels.brightness)
pixels.fill((0, 0, 0))
pixels.show()

def all_off():
    """安全關燈"""
    pixels.fill((0, 0, 0))
    pixels.show()

try:
    # 程式開始前先強制清空 LED（防止之前 REPL 或程式殘留）
    all_off()
    print("LED matrix initialized. Starting demo...")

    # ===== 你要顯示的內容 =====
    # 這裡先示範全紅
    pixels.fill((255, 0, 0))
    pixels.show()

    # 不讓程式結束（否則 LED 會維持紅）
    while True:
        if pixels.brightness < 1:
            pixels.brightness += 0.1
            pixels.show()
            time.sleep(0.2)

except KeyboardInterrupt:
    print("\nDetected Ctrl+C — turning off all LEDs...")
    all_off()
    print("LEDs turned off safely.")
    sys.exit(0)

except Exception as e:
    print("Error occurred:", e)
    all_off()
    sys.exit(1)

