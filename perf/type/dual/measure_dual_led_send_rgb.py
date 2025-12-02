"""
measure_dual_led_color.py

Benchmark RTT + Pico LED fill time over UART using COLOR R G B protocol.
"""

import time
import statistics as stats
import os
import sys
import argparse
import random
import serial

# ----- Import save_result -----
CURRENT_DIR = os.path.dirname(__file__)
TESTS_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if TESTS_DIR not in sys.path:
    sys.path.append(TESTS_DIR)

from save_result import save_test_result

# ----- Configuration -----
DEFAULT_PORT = "/dev/ttyAMA3"
BAUD = 115200
N_SAMPLES = 500
SLEEP_INTERVAL = 0   # slightly slower to prevent Pico overflow


def percentile(sorted_list, p: float):
    n = len(sorted_list)
    if n == 0:
        return None
    idx = min(int(p * n), n - 1)
    return sorted_list[idx]


def open_uart(port: str) -> serial.Serial:
    ser = serial.Serial(port, BAUD, timeout=1.0)
    time.sleep(1.0)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def main(run_id: str | None, port: str):
    ser = open_uart(port)
    print(f"[dual] UART open: {port} @ {BAUD}")

    rtts = []
    pico_times = []

    print(f"[dual] Running {N_SAMPLES} COLOR samples...")

    for i in range(N_SAMPLES):

        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        cmd = f"COLOR {r} {g} {b}\n".encode("utf-8")

        t0 = time.monotonic_ns()
        ser.write(cmd)
        ser.flush()

        reply_bytes = ser.readline()
        t1 = time.monotonic_ns()

        if not reply_bytes:
            print(f"WARNING: No reply sample {i}")
            continue

        reply = reply_bytes.decode("utf-8", errors="ignore").strip()
        rtt_ms = (t1 - t0) / 1e6
        rtts.append(rtt_ms)

        # parse DONE <ms>
        parts = reply.split()
        if len(parts) == 2 and parts[0] == "DONE":
            try:
                pico_times.append(float(parts[1]))
            except:
                pass

        if i % 50 == 0:
            print(f"  {i}/{N_SAMPLES} RTT={rtt_ms:.3f}ms reply={reply}")

        time.sleep(SLEEP_INTERVAL)

    ser.close()

    # ---- Stats ----
    rtts.sort()
    pico_times.sort()

    results = {
        "samples_rtt": len(rtts),
        "avg_rtt_ms": stats.mean(rtts),
        "median_rtt_ms": stats.median(rtts),
        "max_rtt_ms": max(rtts),
        "p95_rtt_ms": percentile(rtts, 0.95),
        "p99_rtt_ms": percentile(rtts, 0.99),
        "samples_pico": len(pico_times),
        "pico_avg_ms": stats.mean(pico_times),
        "pico_median_ms": stats.median(pico_times),
        "pico_max_ms": max(pico_times),
        "pico_p95_ms": percentile(pico_times, 0.95),
        "pico_p99_ms": percentile(pico_times, 0.99),
        "sleep_interval_s": SLEEP_INTERVAL,
        "uart_port": port,
        "baud": BAUD,
    }

    print("\n==== Pi+Pico COLOR RTT stats (ms) ====")
    print(results)

    save_test_result("dual_led_color", results, run_id=run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--port", type=str, default=DEFAULT_PORT)
    args = parser.parse_args()

    main(args.run_id, args.port)
