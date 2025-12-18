# ir_test_all.py
#
# Test 5× VL53L0X sensors at the same time.
# - Initialize 5 sensors via XSHUT pins
# - Assign unique I2C addresses 0x30 ~ 0x34
# - Only print when any sensor "detects" something (distance < THRESHOLD)
# - Each line prints absolute timestamp + all triggered sensors

import time
import datetime

import board
import busio
import digitalio
import adafruit_vl53l0x

# Wiring config (must match your real wiring)
XSHUT_PINS = [
    board.D21,  # Sensor 0
    board.D20,  # Sensor 1
    board.D16,  # Sensor 2
    board.D26,  # Sensor 3
    board.D12,  # Sensor 4
]

BASE_ADDR = 0x30  # 0x30 ~ 0x34
# 偵測門檻：距離小於這個值時才算「有感測到」(自己照實際高度調)
DETECTION_THRESHOLD_MM = 220


def init_sensors(i2c):
    """Bring up 5 sensors one-by-one and assign unique addresses."""
    xshut_ios = []
    for pin in XSHUT_PINS:
        dio = digitalio.DigitalInOut(pin)
        dio.direction = digitalio.Direction.OUTPUT
        dio.value = False  # shutdown all
        xshut_ios.append(dio)

    time.sleep(0.05)

    sensors = []

    for idx, dio in enumerate(xshut_ios):
        # Turn on only this sensor
        dio.value = True
        time.sleep(0.05)

        # init at default address 0x29
        sensor = adafruit_vl53l0x.VL53L0X(i2c)
        new_addr = BASE_ADDR + idx
        sensor.set_address(new_addr)
        print(f"Sensor[{idx}] initialized at I2C address 0x{new_addr:02X}")
        sensors.append(sensor)

    print("All sensors initialized.\n")
    return sensors


def now_str():
    """Return human-readable absolute time with milliseconds."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main():
    print("=== VL53L0X 5-Sensors Test ===")
    print("Only print when distance < "
          f"{DETECTION_THRESHOLD_MM} mm on any sensor.\n")

    i2c = busio.I2C(board.SCL, board.SDA)
    sensors = init_sensors(i2c)

    print("=== Reading distances (mm) ===")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            active_readings = []

            for idx, sensor in enumerate(sensors):
                try:
                    dist = sensor.range  # may raise exception
                except Exception:
                    dist = -1

                # 判斷「有感測到」的條件（可依需求調整）
                if 0 < dist <= DETECTION_THRESHOLD_MM:
                    active_readings.append((idx, dist))

            if active_readings:
                ts = now_str()
                # e.g. "S0= 120mm S3= 135mm ..."
                reading_str = " ".join(
                    f"S{idx}={dist:4d}mm" for idx, dist in active_readings
                )
                print(f"{ts} | {reading_str}")

            # loop 間隔自己調，越小越即時、CPU/ I2C 負擔越重
            time.sleep(0.03)

    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
