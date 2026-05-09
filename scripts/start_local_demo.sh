#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MOCK_PORT="${MOCK_PORT:-50990}"
RUNTIME_HOST="${RUNTIME_HOST:-127.0.0.1}"
RUNTIME_PORT="${RUNTIME_PORT:-50200}"
WORKER_BASE_PORT="${WORKER_BASE_PORT:-50210}"
PANEL_PORT="${PANEL_PORT:-50280}"
MIN_WORKERS="${MIN_WORKERS:-1}"
MAX_WORKERS="${MAX_WORKERS:-2}"
RUNTIME_HOME="${RUNTIME_HOME:-.yizutt/runtime}"
PANEL_HISTORY="${PANEL_HISTORY:-.yizutt/panel/history.sqlite3}"
LOG_DIR="${LOG_DIR:-.yizutt/local-demo/logs}"
BUILD="${BUILD:-1}"
RECOVERY_MODE="${RECOVERY_MODE:-none}"

RUNTIME_BIN="${RUNTIME_BIN:-target/debug/yizutt-runtime}"
RUNTIME_ADDR="http://${RUNTIME_HOST}:${RUNTIME_PORT}"
LOCAL_MODEL_URL="${YIZUTT_LOCAL_MODEL_URL:-http://127.0.0.1:${MOCK_PORT}}"
PANEL_URL="http://127.0.0.1:${PANEL_PORT}"

MOCK_PID=""
RUNTIME_PID=""
PANEL_PID=""

cleanup() {
  for pid in "$PANEL_PID" "$RUNTIME_PID" "$MOCK_PID"; do
    if [[ -n "${pid:-}" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
}

wait_for_runtime() {
  for _ in $(seq 1 40); do
    if "$RUNTIME_BIN" status --addr "$RUNTIME_ADDR" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "Runtime failed to become ready. See ${LOG_DIR}/runtime.log" >&2
  return 1
}

wait_for_mock() {
  for _ in $(seq 1 40); do
    if python - "$LOCAL_MODEL_URL" >/dev/null 2>&1 <<'PY'
import sys
from urllib.request import Request, urlopen

request = Request(
    sys.argv[1],
    data=b'{"prompt":"ping"}',
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request, timeout=1) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
    then
      return 0
    fi
    sleep 0.5
  done
  echo "Mock model failed to become ready. See ${LOG_DIR}/mock-model.log" >&2
  return 1
}

wait_for_panel() {
  for _ in $(seq 1 40); do
    if python - "$PANEL_URL/api/config" >/dev/null 2>&1 <<'PY'
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=1) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
    then
      return 0
    fi
    sleep 0.5
  done
  echo "Panel failed to become ready. See ${LOG_DIR}/panel.log" >&2
  return 1
}

case "$RECOVERY_MODE" in
  none) RECOVERY_ARGS=() ;;
  resume) RECOVERY_ARGS=(--resume-incomplete-tasks) ;;
  expire) RECOVERY_ARGS=(--expire-incomplete-tasks) ;;
  *)
    echo "RECOVERY_MODE must be one of: none, resume, expire" >&2
    exit 2
    ;;
esac

trap cleanup EXIT INT TERM

mkdir -p "$LOG_DIR" "$(dirname "$PANEL_HISTORY")" "$RUNTIME_HOME"

if [[ "$BUILD" != "0" ]]; then
  cargo build --workspace --locked
fi

export PYTHONPATH="${ROOT_DIR}/python${PYTHONPATH:+:${PYTHONPATH}}"

python examples/local_mock_model.py --port "$MOCK_PORT" >"${LOG_DIR}/mock-model.log" 2>&1 &
MOCK_PID=$!
wait_for_mock

YIZUTT_LOCAL_MODEL_URL="$LOCAL_MODEL_URL" "$RUNTIME_BIN" run \
  --bind "${RUNTIME_HOST}:${RUNTIME_PORT}" \
  --worker-base-port "$WORKER_BASE_PORT" \
  --min-workers "$MIN_WORKERS" \
  --max-workers "$MAX_WORKERS" \
  --home "$RUNTIME_HOME" \
  "${RECOVERY_ARGS[@]}" \
  >"${LOG_DIR}/runtime.log" 2>&1 &
RUNTIME_PID=$!

wait_for_runtime

python -m yizutt_agi.panel \
  --port "$PANEL_PORT" \
  --runtime-addr "$RUNTIME_ADDR" \
  --runtime-bin "$RUNTIME_BIN" \
  --runtime-home "$RUNTIME_HOME" \
  --history-path "$PANEL_HISTORY" \
  >"${LOG_DIR}/panel.log" 2>&1 &
PANEL_PID=$!

wait_for_panel

cat <<EOF
Yizutt local demo is running.

Panel:   ${PANEL_URL}
Runtime: ${RUNTIME_ADDR}
Logs:    ${LOG_DIR}

Submit from another terminal:
  ${RUNTIME_BIN} submit --addr ${RUNTIME_ADDR} --session demo --task "Use the read_file tool to read README.md, then summarize the project in one sentence." --context-json '{"provider":"local","max_tool_steps":2}'

Press Ctrl-C to stop mock model, Runtime, and panel.
EOF

wait
