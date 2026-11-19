#!/usr/bin/env bash
# PHASE 3 (step 2) - deploy the hardened collector (operational-observation flow
# + the IEC-104 command-field whitelist) and restart it.
#
# The deploy pipeline's embedded heredoc produced an older collector that writes
# defender_observation_events.jsonl but NOT defender_operational_observation_events.jsonl.
# setup_patches/telemetry_ground_truth/telemetry_collector_service.py is the hardened
# build: it adds build_operational_observation()/OPERATIONAL_LOG AND whitelists the
# IEC-104 command fields (command_phase, asdu_type, cause, common_address) the live
# episode's SELECT evidence requires. Apply setup_patches first (see RUNBOOK), then run.
set -u
COL="${COLLECTOR_HOST:-collector}"
SRC="$HOME/ecpomdg_setup/telemetry_ground_truth/telemetry_collector_service.py"
APP="ecpomdg/telemetry_ground_truth/app"
LOGS="ecpomdg/telemetry_ground_truth/logs"

echo "== 0. sanity: operational code + command-field whitelist present =="
grep -q "OPERATIONAL_LOG" "$SRC"  || { echo ">>> $SRC lacks OPERATIONAL_LOG";  exit 1; }
grep -q "command_phase" "$SRC"    || { echo ">>> $SRC lacks command_phase whitelist"; exit 1; }
echo "    OK ($(wc -l < "$SRC") lines)"

echo "== 1. stop collector =="
ssh "$COL" "~/$APP/stop_telemetry_collector_service.sh" || true

echo "== 2. ship hardened collector + compile-check =="
scp -q "$SRC" "$COL:$APP/telemetry_collector_service.py" || { echo ">>> scp failed"; exit 2; }
ssh "$COL" "python3 -m py_compile ~/$APP/telemetry_collector_service.py" || { echo ">>> py_compile failed"; exit 3; }

echo "== 3. start collector + confirm listening (9201 ingress / 9202 obs) =="
ssh "$COL" "~/$APP/start_telemetry_collector_service.sh" || { echo ">>> start failed"; exit 4; }
ssh "$COL" "ss -lntp | grep -E ':9201|:9202' || echo '>>> ports NOT listening'"

echo "== 4. current counts =="
ssh "$COL" "cd ~/$LOGS && for f in defender_observation_events defender_operational_observation_events; do printf '    %-45s ' \"\$f.jsonl:\"; test -f \$f.jsonl && wc -l < \$f.jsonl || echo 0; done"
