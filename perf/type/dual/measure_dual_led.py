"""
measure_dual_led.py

Measure the round-trip latency of controlling a NeoPixel LED strip
via a dual-machine setup: Raspberry Pi 5 + Raspberry Pi Pico.

Protocol:
- Raspberry Pi sends "LED_TEST\n" over UART to the Pico.
- Pico receives the command, performs a full-strip ON/OFF cycle
  on its NeoPixel strip, measures local time in ms, and replies:
    "DONE <pico_ms>\n"
- Pi measures the round-trip time (RTT) between write and read.

This script:
- Runs N_SAMPLES LED_TEST commands.
- Records RTT on Pi side (ms).
- Parses and records Pico's local LED time (ms) if present.
- Reports avg / median / max / p95 / p99 for RTT and Pico times.
- Saves the results via tests/save_result.py.
"""

import time
import statistics as stats
import os
import sys
import argparse

import serial  # pyserial

# ----- Import the shared save_result utility -----
CURRENT_DIR = os.path.dirname(__file__)
TESTS_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if TESTS_DIR not in sys.path:
    sys.path.append(TESTS_DIR)

from save_result import save_test_result  # noqa: E402


# ----- Configuration -----
DEFAULT_PORT = "/dev/ttyAMA3"  # UART device on Raspberry Pi
BAUD = 115200
N_SAMPLES = 500
SLEEP_INTERVAL = 0.02          # Delay between commands (seconds)


def percentile(sorted_list, p: float):
    """Return p-th percentile from a sorted list (p in [0.0, 1.0])."""
    n = len(sorted_list)
    if n == 0:
        return None
    idx = min(int(p * n), n - 1)
    return sorted_list[idx]


def open_uart(port: str) -> serial.Serial:
    """
    Open the UART port to the Pico and clear any stale data.
    """
    ser = serial.Serial(port, BAUD, timeout=1.0)
    # Give the Pico some time to boot / print banner if needed
    time.sleep(1.0)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def main(run_id: str | None, port: str):
    ser = open_uart(port)
    print(f"[dual] Opened UART port: {port} @ {BAUD} baud")

    # Optional warm-up PINGs (requires Pico to handle "PING")
    try:
        print("[dual] Warm-up PING tests...")
        for i in range(3):
            t0 = time.monotonic_ns()
            ser.write(b"PING\n")
            ser.flush()
            reply = ser.readline().decode("utf-8", errors="ignore").strip()
            t1 = time.monotonic_ns()
            rtt_ms = (t1 - t0) / 1e6
            print(f"  PING {i}: reply={repr(reply)}, RTT={rtt_ms:.3f} ms")
    except Exception as e:
        print("[dual] Warm-up PING failed or not supported:", e)

    rtts = []        # Round-trip times on Pi side
    pico_times = []  # Pico local LED times, parsed from "DONE <ms>"

    print(f"[dual] Measuring {N_SAMPLES} LED_TEST samples...")

    for i in range(N_SAMPLES):
        t0 = time.monotonic_ns()
        ser.write(b"LED_TEST\n")
        ser.flush()
        reply_bytes = ser.readline()  # blocks up to timeout
        t1 = time.monotonic_ns()

        if not reply_bytes:
            # No reply (timeout) — you can choose to skip or record as None/NaN
            print(f"  WARNING: No reply for sample {i}")
            continue

        reply = reply_bytes.decode("utf-8", errors="ignore").strip()
        rtt_ms = (t1 - t0) / 1e6
        rtts.append(rtt_ms)

        # Try to parse "DONE <pico_ms>"
        parts = reply.split()
        if len(parts) == 2 and parts[0] == "DONE":
            try:
                pico_ms = float(parts[1])
                pico_times.append(pico_ms)
            except ValueError:
                pass

        if i > 0 and i % 50 == 0:
            print(f"  sample {i}/{N_SAMPLES}, RTT={rtt_ms:.3f} ms, reply={repr(reply)}")

        time.sleep(SLEEP_INTERVAL)

    ser.close()

    # ---- Compute stats for Pi-side RTT ----
    rtts.sort()
    n_rtt = len(rtts)

    avg_rtt = stats.mean(rtts) if n_rtt > 0 else None
    median_rtt = stats.median(rtts) if n_rtt > 0 else None
    max_rtt = max(rtts) if n_rtt > 0 else None
    p95_rtt = percentile(rtts, 0.95)
    p99_rtt = percentile(rtts, 0.99)

    print("\n==== Pi+Pico DUAL LED_TEST RTT stats (ms) ====")
    print("Samples :", n_rtt)
    print("Avg RTT :", avg_rtt)
    print("Median  :", median_rtt)
    print("Max RTT :", max_rtt)
    print("p95 RTT :", p95_rtt)
    print("p99 RTT :", p99_rtt)

    # ---- Pico local LED timing stats ----
    pico_avg = pico_med = pico_max = pico_p95 = pico_p99 = None
    n_pico = len(pico_times)

    if pico_times:
        pico_times.sort()
        pico_avg = stats.mean(pico_times)
        pico_med = stats.median(pico_times)
        pico_max = max(pico_times)
        pico_p95 = percentile(pico_times, 0.95)
        pico_p99 = percentile(pico_times, 0.99)

        print("\n---- Pico local LED_TEST time (ms) ----")
        print("Samples :", n_pico)
        print("Avg     :", pico_avg)
        print("Median  :", pico_med)
        print("Max     :", pico_max)
        print("p95     :", pico_p95)
        print("p99     :", pico_p99)
    else:
        print("\n(No Pico local times collected; check DONE replies.)")

    # ---- Save to JSON via save_result ----
    results = {
        "samples_rtt": n_rtt,
        "avg_rtt_ms": avg_rtt,
        "median_rtt_ms": median_rtt,
        "max_rtt_ms": max_rtt,
        "p95_rtt_ms": p95_rtt,
        "p99_rtt_ms": p99_rtt,
        "sleep_interval_s": SLEEP_INTERVAL,
        "uart_port": port,
        "baud": BAUD,
        # Pico-side stats
        "samples_pico": n_pico,
        "pico_avg_ms": pico_avg,
        "pico_median_ms": pico_med,
        "pico_max_ms": pico_max,
        "pico_p95_ms": pico_p95,
        "pico_p99_ms": pico_p99,
    }

    # Note: assuming your save_test_result now accepts run_id parameter
    save_test_result("dual_led", results, run_id=run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Measure dual-machine (Pi + Pico) LED latency over UART."
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional run identifier to use in the result filename.",
    )
    parser.add_argument(
        "--port",
        type=str,
        default=DEFAULT_PORT,
        help=f"UART port to use (default: {DEFAULT_PORT}).",
    )
    args = parser.parse_args()

    main(run_id=args.run_id, port=args.port)
