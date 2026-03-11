#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
LIVEKIT_PORT="${LIVEKIT_PORT:-7880}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"
FRONTEND_URL="${FRONTEND_URL:-http://127.0.0.1:${FRONTEND_PORT}}"
LIVEKIT_URL="${LIVEKIT_URL:-ws://127.0.0.1:${LIVEKIT_PORT}}"
DEMO_TUTOR_ID="${DEMO_TUTOR_ID:-demo-tutor}"
DEMO_SESSION_TYPE="${DEMO_SESSION_TYPE:-practice}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"

BACKEND_PID=""
FRONTEND_PID=""
BACKEND_LOG=""
FRONTEND_LOG=""
STARTED_BACKEND=0
STARTED_FRONTEND=0
STARTED_LIVEKIT=0

usage() {
  cat <<EOF
Usage: ./scripts/demo-setup.sh

Starts or reuses the local LiveKit, backend, and frontend demo stack,
waits for health checks to pass, creates a practice-mode demo session,
and prints tutor + student URLs for recording.

Environment overrides:
  BACKEND_PORT            default: 8000
  FRONTEND_PORT           default: 3000
  LIVEKIT_PORT            default: 7880
  DEMO_TUTOR_ID           default: demo-tutor
  DEMO_SESSION_TYPE       default: practice
  WAIT_TIMEOUT_SECONDS    default: 180

Examples:
  make demo-setup
  DEMO_TUTOR_ID="Ada Lovelace" DEMO_SESSION_TYPE=practice ./scripts/demo-setup.sh
EOF
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Error: python3 (or python) is required." >&2
  exit 1
fi

log() {
  printf '==> %s\n' "$*"
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    die "Missing required command: $name"
  fi
}

http_ready() {
  local url="$1"
  "$PYTHON_BIN" - "$url" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=2) as response:
        raise SystemExit(0 if 200 <= response.status < 500 else 1)
except Exception:
    raise SystemExit(1)
PY
}

port_ready() {
  local host="$1"
  local port="$2"
  "$PYTHON_BIN" - "$host" "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1.0)
try:
    raise SystemExit(0 if sock.connect_ex((host, port)) == 0 else 1)
finally:
    sock.close()
PY
}

show_log_tail() {
  local title="$1"
  local file="$2"
  if [ -n "$file" ] && [ -f "$file" ]; then
    printf '\n--- %s (last 40 lines) ---\n' "$title" >&2
    tail -n 40 "$file" >&2 || true
    printf '%s\n\n' '----------------------------------------' >&2
  fi
}

wait_for_http() {
  local label="$1"
  local url="$2"
  local pid="${3:-}"
  local logfile="${4:-}"
  local elapsed=0

  while [ "$elapsed" -lt "$WAIT_TIMEOUT_SECONDS" ]; do
    if http_ready "$url"; then
      log "$label is ready at $url"
      return 0
    fi

    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      show_log_tail "$label log" "$logfile"
      die "$label exited before it became ready"
    fi

    sleep 2
    elapsed=$((elapsed + 2))
  done

  show_log_tail "$label log" "$logfile"
  die "Timed out waiting for $label at $url"
}

wait_for_port() {
  local label="$1"
  local host="$2"
  local port="$3"
  local elapsed=0

  while [ "$elapsed" -lt "$WAIT_TIMEOUT_SECONDS" ]; do
    if port_ready "$host" "$port"; then
      log "$label is ready on ${host}:${port}"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  die "Timed out waiting for $label on ${host}:${port}"
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi

  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi

  if [ "$STARTED_LIVEKIT" -eq 1 ]; then
    (cd "$ROOT_DIR" && docker compose stop livekit >/dev/null 2>&1) || true
  fi

  exit "$exit_code"
}

trap cleanup EXIT INT TERM

require_command docker
require_command node
require_command npm
require_command uv

log "Checking local prerequisites"
log "Python: $($PYTHON_BIN --version 2>&1)"
log "Node: $(node --version)"
log "Docker: $(docker --version)"

if ! port_ready "127.0.0.1" "$LIVEKIT_PORT"; then
  log "LiveKit is not running on port ${LIVEKIT_PORT}; attempting to start docker compose service"
  if ! docker info >/dev/null 2>&1; then
    die "Docker is installed but the daemon is not available. Start Docker Desktop or run a local livekit-server manually."
  fi
  if ! docker compose version >/dev/null 2>&1; then
    die "docker compose is required to auto-start LiveKit."
  fi
  (cd "$ROOT_DIR" && docker compose up -d livekit >/dev/null)
  STARTED_LIVEKIT=1
  wait_for_port "LiveKit" "127.0.0.1" "$LIVEKIT_PORT"
else
  log "Reusing existing LiveKit server on port ${LIVEKIT_PORT}"
fi

if http_ready "${BACKEND_URL}/health"; then
  log "Reusing existing backend at ${BACKEND_URL}"
elif port_ready "127.0.0.1" "$BACKEND_PORT"; then
  die "Port ${BACKEND_PORT} is already in use, but ${BACKEND_URL}/health did not respond."
else
  BACKEND_LOG="$(mktemp -t live-session-analysis-backend.XXXX.log)"
  log "Starting backend (log: ${BACKEND_LOG})"
  (
    cd "$ROOT_DIR/backend"
    export LSA_CORS_ORIGINS='["http://localhost:3000","http://127.0.0.1:3000"]'
    export LSA_ENABLE_LIVEKIT=true
    export LSA_ENABLE_LIVEKIT_ANALYTICS_WORKER=true
    export LSA_LIVEKIT_URL="$LIVEKIT_URL"
    export LSA_LIVEKIT_API_KEY="devkey"
    export LSA_LIVEKIT_API_SECRET="secret"
    exec uv run --python 3.11 --with-requirements requirements.txt \
      uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT"
  ) >"$BACKEND_LOG" 2>&1 &
  BACKEND_PID="$!"
  STARTED_BACKEND=1
  wait_for_http "Backend" "${BACKEND_URL}/health" "$BACKEND_PID" "$BACKEND_LOG"
fi

if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
  log "Installing frontend dependencies"
  (cd "$ROOT_DIR/frontend" && npm install)
fi

if http_ready "$FRONTEND_URL"; then
  log "Reusing existing frontend at ${FRONTEND_URL}"
elif port_ready "127.0.0.1" "$FRONTEND_PORT"; then
  die "Port ${FRONTEND_PORT} is already in use, but ${FRONTEND_URL} did not respond."
else
  FRONTEND_LOG="$(mktemp -t live-session-analysis-frontend.XXXX.log)"
  log "Starting frontend (log: ${FRONTEND_LOG})"
  (
    cd "$ROOT_DIR/frontend"
    export NEXT_PUBLIC_API_URL="$BACKEND_URL"
    export NEXT_PUBLIC_WS_URL="ws://127.0.0.1:${BACKEND_PORT}"
    export NEXT_PUBLIC_LIVEKIT_URL="$LIVEKIT_URL"
    exec npm run dev -- --hostname 0.0.0.0 --port "$FRONTEND_PORT"
  ) >"$FRONTEND_LOG" 2>&1 &
  FRONTEND_PID="$!"
  STARTED_FRONTEND=1
  wait_for_http "Frontend" "$FRONTEND_URL" "$FRONTEND_PID" "$FRONTEND_LOG"
fi

SESSION_RESPONSE="$($PYTHON_BIN - "$BACKEND_URL" "$DEMO_TUTOR_ID" "$DEMO_SESSION_TYPE" <<'PY'
import json
import sys
import urllib.error
import urllib.request

backend_url, tutor_id, session_type = sys.argv[1:4]
payload = json.dumps(
    {
        "tutor_id": tutor_id,
        "session_type": session_type,
        "media_provider": "livekit",
    }
).encode("utf-8")
request = urllib.request.Request(
    f"{backend_url}/api/sessions",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        sys.stdout.write(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8")
    raise SystemExit(f"HTTP {exc.code}: {body or exc.reason}")
except Exception as exc:
    raise SystemExit(str(exc))
PY
)"

SESSION_FIELDS=()
while IFS= read -r line; do
  SESSION_FIELDS+=("$line")
done <<EOF
$($PYTHON_BIN - "$SESSION_RESPONSE" "$FRONTEND_URL" <<'PY'
import json
import sys
import urllib.parse

payload = json.loads(sys.argv[1])
frontend_url = sys.argv[2].rstrip("/")
session_id = payload["session_id"]
tutor_token = payload["tutor_token"]
student_token = payload["student_token"]
quote = urllib.parse.quote

print(session_id)
print(tutor_token)
print(student_token)
print(f"{frontend_url}/session/{quote(session_id)}?token={quote(tutor_token)}")
print(f"{frontend_url}/session/{quote(session_id)}?token={quote(tutor_token)}&debug=1")
print(f"{frontend_url}/session/{quote(session_id)}?token={quote(student_token)}")
print(f"{frontend_url}/analytics/{quote(session_id)}")
PY
)
EOF

if [ "${#SESSION_FIELDS[@]}" -lt 7 ]; then
  die "Failed to parse session creation response: ${SESSION_RESPONSE}"
fi

SESSION_ID="${SESSION_FIELDS[0]}"
TUTOR_TOKEN="${SESSION_FIELDS[1]}"
STUDENT_TOKEN="${SESSION_FIELDS[2]}"
TUTOR_URL="${SESSION_FIELDS[3]}"
TUTOR_DEBUG_URL="${SESSION_FIELDS[4]}"
STUDENT_URL="${SESSION_FIELDS[5]}"
ANALYTICS_URL="${SESSION_FIELDS[6]}"

LIVEKIT_VALIDATION="$($PYTHON_BIN - "$BACKEND_URL" "$SESSION_ID" "$TUTOR_TOKEN" <<'PY'
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

backend_url, session_id, tutor_token = sys.argv[1:4]
query_token = urllib.parse.quote(tutor_token, safe="")
request = urllib.request.Request(
    f"{backend_url}/api/sessions/{urllib.parse.quote(session_id, safe='')}/livekit-token?token={query_token}",
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
        print(payload.get("room_name", ""))
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8")
    raise SystemExit(f"HTTP {exc.code}: {body or exc.reason}")
except Exception as exc:
    raise SystemExit(str(exc))
PY
)"

printf '\n'
log "Demo session created successfully"
printf '  Home page:      %s\n' "$FRONTEND_URL"
printf '  Tutor URL:      %s\n' "$TUTOR_URL"
printf '  Tutor debug:    %s\n' "$TUTOR_DEBUG_URL"
printf '  Student URL:    %s\n' "$STUDENT_URL"
printf '  Analytics URL:  %s\n' "$ANALYTICS_URL"
printf '  Session ID:     %s\n' "$SESSION_ID"
printf '  Session type:   %s\n' "$DEMO_SESSION_TYPE"
printf '  Tutor id:       %s\n' "$DEMO_TUTOR_ID"
printf '  LiveKit room:   %s\n' "$LIVEKIT_VALIDATION"
printf '\n'
printf '%s\n' 'Recommended recording flow:'
printf '%s\n' '  1. Start your screen recorder and open the home page.'
printf '%s\n' '  2. Prefer creating a fresh on-camera session from the UI; keep the URLs above as a backup.'
printf '%s\n' '  3. Open the student link in a second browser or incognito window.'
printf '%s\n' '  4. Show the live tutor/student call, then enable Coach debug on the tutor side.'
printf '%s\n' '  5. After the 120s live-nudge warmup, let the tutor hold the floor in practice mode to trigger a nudge.'
printf '%s\n' '  6. End the session and show the analytics detail page plus the dashboard.'
printf '\n'
printf '%s\n' 'Keep this terminal open while recording if the script started your backend/frontend.'
if [ -n "$BACKEND_LOG" ]; then
  printf '  Backend log:   %s\n' "$BACKEND_LOG"
fi
if [ -n "$FRONTEND_LOG" ]; then
  printf '  Frontend log:  %s\n' "$FRONTEND_LOG"
fi
printf '\n'

if [ "$STARTED_BACKEND" -eq 1 ] || [ "$STARTED_FRONTEND" -eq 1 ]; then
  log "Press Ctrl-C when you are done recording."
  while true; do
    if [ "$STARTED_BACKEND" -eq 1 ] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      show_log_tail "Backend log" "$BACKEND_LOG"
      die "Backend exited unexpectedly"
    fi
    if [ "$STARTED_FRONTEND" -eq 1 ] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      show_log_tail "Frontend log" "$FRONTEND_LOG"
      die "Frontend exited unexpectedly"
    fi
    sleep 2
  done
fi
