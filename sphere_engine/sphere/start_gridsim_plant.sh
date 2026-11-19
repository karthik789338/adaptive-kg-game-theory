#!/usr/bin/env bash
# Start the gridsim plant service on the gridsim node (run ON gridsim).
# Idempotent: kills any prior instance, relaunches, waits for /state.
set -u
APP="$HOME/ecpomdg/t2_gridsim/app/gridsim_plant_service.py"
LOGDIR="$HOME/ecpomdg/t2_gridsim/logs"
BIND="${PLANT_BIND:-0.0.0.0}"
PORT="${PLANT_PORT:-8765}"
mkdir -p "$LOGDIR"

pkill -f "gridsim_plant_service.py" 2>/dev/null && sleep 1 || true

nohup python3 "$APP" --bind "$BIND" --port "$PORT" \
  >"$LOGDIR/plant_service_stdout.log" 2>&1 &
echo "  launched plant (pid $!), waiting for /state ..."

for i in $(seq 1 15); do
  if python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:${PORT}/state',timeout=2)" 2>/dev/null; then
    echo "  PLANT UP on ${BIND}:${PORT}"; exit 0
  fi
  sleep 1
done
echo "  PLANT DID NOT COME UP -- check $LOGDIR/plant_service_stdout.log"; exit 1
