# measure_single_led.py

"""
measure_single_led.py

Measure the latency of directly controlling a NeoPixel LED strip
from Raspberry Pi 5 using Blinka + CircuitPython neopixel.

This variant:
- Lights up ALL LEDs using pixels.fill((255, 0, 0)).
- Measures the time for fill + show in milliseconds.
- Reports avg / median / max / p95 / p99.
- Saves the results via tests/save_result.py.
"""

import time
import statistics as stats
import os
import sys
import argparse
import random
import board
import neopixel

# ----- Import the shared save_result utility -----
CURRENT_DIR = os.path.dirname(__file__)
TESTS_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if TESTS_DIR not in sys.path:
    sys.path.append(TESTS_DIR)

from save_result import save_test_result  # noqa: E402


# ----- Configuration -----
NUM_PIXELS = 512           # Number of LEDs on the strip
PIN = board.D18           # GPIO pin used for NeoPixel data (adjust if needed)
BRIGHTNESS = 0.3          # Global brightness setting for the strip
N_SAMPLES = 500           # How many measurements to run
SLEEP_INTERVAL = 0.02     # Delay between iterations (in seconds)

# Initialize NeoPixel strip on the Pi
pixels = neopixel.NeoPixel(
    PIN,
    NUM_PIXELS,
    brightness=BRIGHTNESS,
    auto_write=False,   # We call .show() manually
)

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

def full_on_random_same():
    """Fill all pixels with the same random color."""
    r = random.randint(0, 255)
    g = random.randint(0, 255)
    b = random.randint(0, 255)
    pixels.fill((r, g, b))
    pixels.show()




def percentile(sorted_list, p: float):
    """Return p-th percentile from a sorted list (p in [0.0, 1.0])."""
    n = len(sorted_list)
    if n == 0:
        return None
    idx = min(int(p * n), n - 1)
    return sorted_list[idx]


def main(run_id: str | None):


    latencies = []

    print(f"[single] Measuring {N_SAMPLES} samples of full-strip LED latency...")

    for i in range(N_SAMPLES):
        t0 = time.monotonic_ns()

        # Turn all pixels ON (red) and show
        full_on_red()

        t1 = time.monotonic_ns()
        lat_ms = (t1 - t0) / 1e6  # ns -> ms
        latencies.append(lat_ms)

        # Turn all pixels OFF
        all_off()

        # Keep a consistent loop frequency
        time.sleep(SLEEP_INTERVAL)

        if i > 0 and i % 50 == 0:
            print(f"  sample {i}/{N_SAMPLES}...")

    latencies.sort()
    n = len(latencies)

    # Compute statistics
    avg = stats.mean(latencies) if n > 0 else None
    median = stats.median(latencies) if n > 0 else None
    max_val = max(latencies) if n > 0 else None
    p95 = percentile(latencies, 0.95)
    p99 = percentile(latencies, 0.99)

    print("\n==== Pi SINGLE (full-strip LED) latency stats (ms) ====")
    print("Samples :", n)
    print("Avg     :", avg)
    print("Median  :", median)
    print("Max     :", max_val)
    print("p95     :", p95)
    print("p99     :", p99)

    # Save results to JSON
    results = {
        "samples": n,
        "avg_ms": avg,
        "median_ms": median,
        "max_ms": max_val,
        "p95_ms": p95,
        "p99_ms": p99,
        "sleep_interval_s": SLEEP_INTERVAL,
        "num_pixels": NUM_PIXELS,
    }
    save_test_result("single_led", results, run_id=run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Measure full-strip LED latency on Raspberry Pi."
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional run identifier to use in the result filename.",
    )
    args = parser.parse_args()

    main(run_id=args.run_id)
