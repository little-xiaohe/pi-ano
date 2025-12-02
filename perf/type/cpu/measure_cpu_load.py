# measure_cpu_load.py

"""
measure_cpu_load.py

Measure system-wide CPU usage on the Raspberry Pi 5 over a given time window.
"""

import time
import os
import sys
import argparse

import psutil

# ----- Import the shared save_result utility -----
CURRENT_DIR = os.path.dirname(__file__)
TESTS_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if TESTS_DIR not in sys.path:
    sys.path.append(TESTS_DIR)

from save_result import save_test_result  # noqa: E402


# ----- Configuration -----
DURATION = 15.0      # Total monitoring time in seconds
INTERVAL = 1.0       # Sampling interval in seconds (psutil.cpu_percent interval)


def main(run_id: str | None):
    print(f"[cpu] Measuring system CPU usage for {DURATION:.1f}s "
          f"(interval={INTERVAL:.1f}s)")
    samples = []

    start_time = time.time()
    end_time = start_time + DURATION

    while time.time() < end_time:
        usage = psutil.cpu_percent(interval=INTERVAL)
        samples.append(usage)
        print(f"CPU: {usage:.1f}%")

    if samples:
        avg_cpu = sum(samples) / len(samples)
        max_cpu = max(samples)

        print("\n==== CPU usage stats (%) ====")
        print("Samples:", len(samples))
        print("Avg    :", avg_cpu)
        print("Max    :", max_cpu)

        results = {
            "samples": len(samples),
            "avg_cpu_percent": avg_cpu,
            "max_cpu_percent": max_cpu,
            "duration_s": DURATION,
            "interval_s": INTERVAL,
        }
        save_test_result("cpu_load", results, run_id=run_id)
    else:
        print("No CPU samples collected; check configuration or timing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Measure system-wide CPU usage on Raspberry Pi."
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional run identifier to use in the result filename.",
    )
    args = parser.parse_args()

    main(run_id=args.run_id)
