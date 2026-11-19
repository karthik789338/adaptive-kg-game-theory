#!/usr/bin/env bash
# PHASE 3 (step 3) - deploy + start the REAL multistage sensor->collector forwarder.
#
# The real controller's _v2 multistage sensor captures the rich IEC-104 stage chain
# (connection_request/session_established/interrogation/point_read/select), but that
# chain only reaches the collector's operational observations through this forwarder.
# It MUST be the enveloped build (POSTs {"event": <dict>}); the old flat build is
# rejected by the hardened collector with HTTP 400. setup_patches holds the enveloped
# copy. Run on the controller host so the collector tags events asset-field-001
# (source IP 10.30.0.10).
set -u
C="${CONTROLLER_HOST:-controller}"
FWD="$HOME/ecpomdg_setup/multistage_game/live_multistage_sensor_build/multistage_live_sensor_forwarder.py"

echo "== 0. sanity: forwarder is the enveloped build =="
grep -q "envelope" "$FWD" || { echo ">>> $FWD is the old flat build (would 400); apply setup_patches"; exit 1; }

echo "== 1. deploy forwarder to controller =="
ssh "$C" "mkdir -p ~/ecpomdg/multistage_live/app ~/ecpomdg/multistage_live/logs"
scp -q "$FWD" "$C:ecpomdg/multistage_live/app/multistage_live_sensor_forwarder.py" || { echo ">>> scp failed"; exit 2; }
ssh "$C" "python3 -m py_compile ~/ecpomdg/multistage_live/app/multistage_live_sensor_forwarder.py" || { echo ">>> compile failed"; exit 3; }

echo "== 2. start (or restart) the forwarder (--mode real) =="
ssh "$C" 'PIDFILE="$HOME/ecpomdg/multistage_live/real_multistage_sensor_forwarder.pid";
LOG="$HOME/ecpomdg/multistage_live/logs/real_multistage_sensor_forwarder.log";
APP="$HOME/ecpomdg/multistage_live/app/multistage_live_sensor_forwarder.py";
if test -f "$PIDFILE"; then OLD="$(cat "$PIDFILE" 2>/dev/null)"; test -n "$OLD" && kill "$OLD" 2>/dev/null; sleep 1; fi;
nohup python3 "$APP" --mode real >>"$LOG" 2>&1 </dev/null & echo $! > "$PIDFILE"; sleep 1;
kill -0 "$(cat "$PIDFILE")" && echo "REAL_MULTISTAGE_SENSOR_FORWARDER: PASS" || { echo FAIL; tail -5 "$LOG"; }'
