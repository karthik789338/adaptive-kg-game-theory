#!/usr/bin/env bash
# =============================================================================
# DEPLOY STEP 0 (must run BEFORE the controller/decoy deploy): push the
# reconstructed gridsim plant service to the gridsim node and start it.
#
# The controller reads the plant's /state on startup, so the plant MUST be
# listening on 10.40.0.20:8765 before deploy_iec104_controller_decoy.sh runs.
# Run on the XDC host (the one with ssh to all nodes).
# =============================================================================
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # ecpomdg_sphere/
GRIDSIM="${GRIDSIM_HOST:-gridsim}"
REMOTE_APP="ecpomdg/t2_gridsim/app"

echo "== deploy gridsim plant -> $GRIDSIM =="
ssh -o ConnectTimeout=8 "$GRIDSIM" "mkdir -p ~/$REMOTE_APP ~/ecpomdg/t2_gridsim/logs" \
  || { echo "  ERROR: cannot ssh/mkdir on $GRIDSIM"; exit 1; }

scp -q "$HERE/sphere/gridsim_plant_service.py" "$GRIDSIM:~/$REMOTE_APP/gridsim_plant_service.py" \
  || { echo "  ERROR: scp plant service failed"; exit 1; }
scp -q "$HERE/sphere/start_gridsim_plant.sh"  "$GRIDSIM:~/$REMOTE_APP/start_gridsim_plant.sh" \
  || { echo "  ERROR: scp start script failed"; exit 1; }

echo "== start gridsim plant =="
ssh -o ConnectTimeout=8 "$GRIDSIM" "bash ~/$REMOTE_APP/start_gridsim_plant.sh" \
  || { echo "  ERROR: plant failed to start on $GRIDSIM"; exit 1; }

echo "== verify plant reachable from the controller node =="
STATE="import urllib.request;print(urllib.request.urlopen('http://10.40.0.20:8765/state',timeout=6).read()[:80])"
if ssh -o ConnectTimeout=8 controller "python3 -c \"$STATE\"" 2>/dev/null; then
  echo "  PASS: controller can read plant /state"
else
  echo "  WARN: plant up on gridsim but controller could not reach 10.40.0.20:8765 (check routing/bind)"
fi
echo "gridsim plant deploy done."
