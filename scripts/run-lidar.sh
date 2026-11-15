#!/usr/bin/env bash
# Sets up the bridge if needed, then starts the viewer and the LiDAR bridge together.
# macOS and Linux. On Windows run the commands in README.md by hand.
#
#   scripts/run-lidar.sh                    live: phone publishes, session recorded
#   scripts/run-lidar.sh --fake             live, plus the SYNTHETIC publisher
#   scripts/run-lidar.sh --replay FILE      replay a recorded session
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
port="${PORT:-4173}"
origin="http://127.0.0.1:${port}"
mode="live"
replay=""
case "${1:-}" in
  "") ;;
  --fake) mode="fake" ;;
  --replay)
    mode="replay"
    replay="${2:-}"
    [ -f "$replay" ] || { echo "Recording not found: ${replay:-<none given>}" >&2; exit 2; }
    replay="$(cd "$(dirname "$replay")" && pwd)/$(basename "$replay")"
    ;;
  *) echo "Usage: scripts/run-lidar.sh [--fake | --replay FILE]" >&2; exit 2 ;;
esac

command -v node >/dev/null || { echo "Node 20+ is required (brew install node)." >&2; exit 1; }

# The bridge needs Python 3.11+. macOS ships 3.9, so look for a newer one first.
python=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null &&
     "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
    python="$candidate"
    break
  fi
done
[ -n "$python" ] || { echo "Python 3.11+ is required (brew install python@3.12)." >&2; exit 1; }

bridge="$root/websocket-bridge"
if [ ! -x "$bridge/.venv/bin/python" ]; then
  echo "Setting up the bridge environment with $python ..."
  "$python" -m venv "$bridge/.venv"
  "$bridge/.venv/bin/pip" install --quiet -e "$bridge"
fi

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$root" && PORT="$port" node serve.js) &
pids+=($!)

cd "$bridge"
if [ "$mode" = "replay" ]; then
  .venv/bin/python -B -m sonar_bridge --lidar-replay "$replay" --origin "$origin" &
else
  mkdir -p "$root/recordings"
  recording="$root/recordings/session-$(date +%Y%m%d-%H%M%S).jsonl"
  .venv/bin/python -B -m sonar_bridge --lidar --record "$recording" --origin "$origin" &
fi
pids+=($!)

if [ "$mode" = "fake" ]; then
  sleep 2
  echo "Starting the SYNTHETIC publisher. This is not real LiDAR data."
  .venv/bin/python -B fake_phone.py &
  pids+=($!)
fi

echo
echo "Open $origin and click Connect. Press Ctrl+C here to stop everything."
wait
