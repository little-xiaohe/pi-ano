# ir_test_all.py
#
# Test 5× VL53L0X sensors at the same time (CONTINUOUS MODE).
# - Initialize 5 sensors via XSHUT pins
# - Assign unique I2C addresses 0x30 ~ 0x34
# - Start continuous ranging on each sensor
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

DETECTION_THRESHOLD_MM = 220  # Detection threshold: only considered detected if distance is less than this value


# Continuous mode timing budget in microseconds.
# 33000us = 33ms (NOT 200ms). Try 100000 (100ms) or 200000 (200ms) for more stability.
TIMING_BUDGET_US = 100_000


# More stable bring-up delay (multi-sensor)
POWER_ON_DELAY_S = 0.15


def init_sensors(i2c):
    """Bring up 5 sensors one-by-one, assign unique addresses, and start continuous mode."""
    xshut_ios = []
    for pin in XSHUT_PINS:
        dio = digitalio.DigitalInOut(pin)
        dio.direction = digitalio.Direction.OUTPUT
        dio.value = False  # shutdown all sensors
        xshut_ios.append(dio)

    time.sleep(0.10)

    sensors = []

    for idx, dio in enumerate(xshut_ios):
        # Turn on only this sensor
        dio.value = True
        time.sleep(POWER_ON_DELAY_S)

        # init at default address 0x29
        sensor = adafruit_vl53l0x.VL53L0X(i2c)

        # assign unique address
        new_addr = BASE_ADDR + idx
        sensor.set_address(new_addr)

        # configure + start continuous ranging
        sensor.measurement_timing_budget = TIMING_BUDGET_US
        sensor.start_continuous()

        print(
            f"Sensor[{idx}] initialized at I2C address 0x{new_addr:02X} | "
            f"timing_budget={TIMING_BUDGET_US}us | continuous=ON"
        )
        sensors.append(sensor)

    print("All sensors initialized.\n")
    return sensors


def now_str():
    """Return human-readable absolute time with milliseconds."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main():
    print("=== VL53L0X 5-Sensors Test (continuous mode) ===")
    print(
        f"Only print when distance < {DETECTION_THRESHOLD_MM} mm on any sensor.\n"
        f"Timing budget = {TIMING_BUDGET_US}us\n"
    )

    i2c = busio.I2C(board.SCL, board.SDA)
    sensors = init_sensors(i2c)

    print("=== Reading distances (mm) ===")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            active_readings = []

            for idx, sensor in enumerate(sensors):
                try:
                    dist = sensor.range  # in continuous mode, this reads latest measurement
                except Exception:
                    dist = -1

                if 0 < dist <= DETECTION_THRESHOLD_MM:
                    active_readings.append((idx, dist))

            if active_readings:
                ts = now_str()
                reading_str = " ".join(
                    f"S{idx}={dist:4d}mm" for idx, dist in active_readings
                )
                print(f"{ts} | {reading_str}")

            # You can reduce this (e.g., 0.02) if you want faster logging,
            # but continuous timing budget is the main limiter for new data.
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nStopping continuous mode...")
        for s in sensors:
            try:
                s.stop_continuous()
            except Exception:
                pass
        print("Stopped.")


if __name__ == "__main__":
    main()
