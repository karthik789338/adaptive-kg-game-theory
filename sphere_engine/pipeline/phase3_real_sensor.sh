#!/usr/bin/env bash
# =============================================================================
# PHASE 3 (step 1) - switch the REAL controller to its multi-stage sensor so
# attacker IEC-104 traffic is captured as stage events (the piece missing for
# live operational observations and live episodes).
#
# Uses the SOURCE-DERIVED endpoint (AST-injects install_multistage_sensor after
# the server is created) -- no c104.Server monkeypatch, so no callback bug.
#
# Run on the XDC host. The real controller endpoint must be running (it is).
# =============================================================================
set -u
C="${CONTROLLER_HOST:-controller}"
SM="$HOME/ecpomdg_setup/multistage_game"
APP="ecpomdg/multistage_live/app"

echo "== 1. deploy sensor + source-derived builder + real switch to the controller =="
ssh "$C" "mkdir -p ~/$APP ~/ecpomdg/multistage_live/logs ~/ecpomdg/multistage_live/audit" || { echo "ssh/mkdir failed"; exit 1; }
scp -q "$SM/live_multistage_sensor_build/multistage_live_sensor.py" "$C:~/$APP/" || { echo "scp sensor failed"; exit 1; }
scp -q "$SM/build_source_derived_multistage_endpoint.py" "$C:~/$APP/"            || { echo "scp builder failed"; exit 1; }
scp -q "$SM/switch_real_controller_to_source_derived_multistage_endpoint.py" "$C:~/$APP/" || { echo "scp switch failed"; exit 1; }

echo "== 2. build the source-derived _v2 endpoint on the controller =="
ssh "$C" "cd ~/$APP && python3 build_source_derived_multistage_endpoint.py" || { echo ">>> build failed"; exit 2; }

echo "== 3. switch the real controller to the _v2 multistage endpoint =="
ssh "$C" "python3 ~/$APP/switch_real_controller_to_source_derived_multistage_endpoint.py" || { echo ">>> switch failed (rolled back to plain endpoint)"; exit 3; }

echo "== 4. verify listener + sensor log path =="
ssh "$C" "ss -ltn | grep -q '10.30.0.10:2404' && echo 'REAL :2404 UP' || echo 'REAL :2404 DOWN'"
ssh "$C" "test -f ~/ecpomdg/multistage_live/logs/iec104_real_multistage_sensor_events.jsonl && echo 'real multistage sensor log present' || echo 'sensor log not yet (created on first captured traffic)'"
echo
echo "Next: generate one attack to populate the real sensor + operational observations:"
echo "  ssh attacker '~/ecpomdg/venvs/iec104_attack/bin/python ~/ecpomdg/industroyer_inspired_iec104/app/industroyer_inspired_iec104_emulator.py --target real --scenario p_curtail'"
echo "  ssh controller 'wc -l ~/ecpomdg/multistage_live/logs/iec104_real_multistage_sensor_events.jsonl'"
