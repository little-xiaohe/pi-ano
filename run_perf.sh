#!/bin/bash
# Run performance tests for Pi-ano.
# Usage:
#   ./run_perf.sh single   # Pi-only LED + CPU
#   ./run_perf.sh dual     # Pi+Pico LED (USB) + CPU
#
# JSON results for the run are saved in:
#   tests/results/run_<MODE>_<RUN_ID>/

set -e

MODE="${1:-single}"   # default = single

if [[ "$MODE" != "single" && "$MODE" != "dual" ]]; then
  echo "Usage: $0 {single|dual}"
  exit 1
fi

# ---- Activate venv ----
source .venv/bin/activate

RESULT_BASE="tests/results"
mkdir -p "$RESULT_BASE"

RUN_ID=$(date +"%Y%m%d_%H%M%S")
RUN_DIR="${RESULT_BASE}/run_${MODE}_${RUN_ID}"
mkdir -p "$RUN_DIR"

echo "[RUN $RUN_ID] Mode=$MODE"
echo "  Result dir: $RUN_DIR"
echo

PID_SINGLE=""
PID_DUAL=""

# ---- SINGLE MODE ----
if [[ "$MODE" == "single" ]]; then
  echo "Starting SINGLE LED test..."
  python tests/performance/single/measure_single_led.py --run-id "$RUN_ID" &
  PID_SINGLE=$!
  echo "  SINGLE PID: $PID_SINGLE"
fi

# ---- DUAL MODE ----
if [[ "$MODE" == "dual" ]]; then
  echo "Starting DUAL LED test (Pi + Pico)..."
  python tests/performance/dual/measure_dual_led_send_rgb.py --run-id "$RUN_ID" &
  PID_DUAL=$!
  echo "  DUAL PID:   $PID_DUAL"
fi

# ---- CPU LOAD ALWAYS RUNS ONCE ----
echo
echo "Starting CPU load test..."
python tests/performance/cpu/measure_cpu_load.py --run-id "$RUN_ID"

# ---- Wait for LED tests ----
echo
echo "Waiting for LED tests..."

if [[ -n "$PID_SINGLE" ]]; then
  wait "$PID_SINGLE"
fi

if [[ -n "$PID_DUAL" ]]; then
  wait "$PID_DUAL"
fi

echo
echo "[RUN $RUN_ID] All tests finished. Collecting JSON..."

# Move all JSONs with this RUN_ID into result folder
mv "${RESULT_BASE}"/*_"$RUN_ID".json "$RUN_DIR"/ 2>/dev/null || true

echo "[DONE] Results saved under:"
echo "  $RUN_DIR"
echo
