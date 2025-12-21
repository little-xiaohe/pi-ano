# ir_test_all_arg.py
#
# VL53L0X test with CLI argument to select sensors
#
# Usage examples:
#   python3 ir_test_all_arg.py --sensor 2
#   python3 ir_test_all_arg.py --sensor 1 3 4

import time
import datetime
import argparse

import board
import busio
import digitalio
import adafruit_vl53l0x


# ----------------------------
# Hardware config
# ----------------------------
XSHUT_PINS = [
    board.D21,  # Sensor 0
    board.D20,  # Sensor 1
    board.D16,  # Sensor 2
    board.D26,  # Sensor 3
    board.D12,  # Sensor 4
]

BASE_ADDR = 0x30  # 0x30~0x34

# ----------------------------
# Sensor config
# ----------------------------
DETECTION_THRESHOLD_MM = 220

# Continuous mode timing budget (microseconds)
TIMING_BUDGET_US = 100_000  # try 100000 or 200000 for stability

POWER_ON_DELAY_S = 0.15
LOOP_SLEEP_S = 0.05


# ----------------------------
# Helpers
# ----------------------------
def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def parse_args():
    parser = argparse.ArgumentParser(
        description="VL53L0X continuous-mode test with selectable sensors"
    )
    parser.add_argument(
        "--sensor",
        type=int,
        nargs="+",
        required=True,
        help="Sensor indices to enable (0~4), e.g. --sensor 2 or --sensor 1 3 4",
    )
    args = parser.parse_args()

    sensors = set(args.sensor)
    invalid = [s for s in sensors if s < 0 or s >= len(XSHUT_PINS)]
    if invalid:
        parser.error(f"Invalid sensor index: {invalid}. Valid range is 0~4.")

    return sensors


def init_selected_sensors(i2c, active_sensors):
    """Only power on sensors listed in active_sensors."""
    xshut_ios = []
    for pin in XSHUT_PINS:
        dio = digitalio.DigitalInOut(pin)
        dio.direction = digitalio.Direction.OUTPUT
        dio.value = False  # shutdown all sensors
        xshut_ios.append(dio)

    time.sleep(0.10)

    sensors = {}
    for idx, dio in enumerate(xshut_ios):
        if idx not in active_sensors:
            continue  # keep it off

        dio.value = True
        time.sleep(POWER_ON_DELAY_S)

        sensor = adafruit_vl53l0x.VL53L0X(i2c)

        new_addr = BASE_ADDR + idx
        sensor.set_address(new_addr)

        sensor.measurement_timing_budget = TIMING_BUDGET_US
        sensor.start_continuous()

        print(
            f"Sensor[{idx}] ON  addr=0x{new_addr:02X} | "
            f"timing_budget={TIMING_BUDGET_US}us | continuous=ON"
        )

        sensors[idx] = sensor

    print("Selected sensors initialized.\n")
    return sensors


# ----------------------------
# Main
# ----------------------------
def main():
    active_sensors = parse_args()

    print("=== VL53L0X Test (CLI selectable sensors) ===")
    print(f"Enabled sensors: {sorted(active_sensors)}")
    print(
        f"Continuous mode, timing_budget={TIMING_BUDGET_US}us\n"
        f"Print when distance < {DETECTION_THRESHOLD_MM} mm\n"
    )

    i2c = busio.I2C(board.SCL, board.SDA)
    sensors = init_selected_sensors(i2c, active_sensors)

    try:
        while True:
            active_readings = []

            for idx, sensor in sensors.items():
                try:
                    dist = sensor.range
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

            time.sleep(LOOP_SLEEP_S)

    except KeyboardInterrupt:
        print("\nStopping continuous mode...")
        for s in sensors.values():
            try:
                s.stop_continuous()
            except Exception:
                pass
        print("Stopped.")


if __name__ == "__main__":
    main()
