#!/usr/bin/env bash
# =============================================================================
# Preflight for the LIVE H1 episode: checks every endpoint h1_live_episode.py
# needs, and reports PASS/DOWN per check WITHOUT aborting. Run on the
# orchestration host (the one with ssh to all nodes). Fix anything DOWN, then
# run the live episode.
# =============================================================================
set -u
PASS=0; FAIL=0
ok(){ echo "  PASS  $1"; PASS=$((PASS+1)); }
no(){ echo "  DOWN  $1  --> $2"; FAIL=$((FAIL+1)); }

echo "== ssh reachability to each node =="
for h in attacker controller decoy collector gridsim defender; do
  if out=$(ssh -o ConnectTimeout=6 -o BatchMode=yes "$h" hostname 2>&1); then ok "ssh $h ($out)"; else no "ssh $h" "$out"; fi
done

echo "== IEC-104 listeners (expected :2404) =="
if ssh -o ConnectTimeout=6 controller "ss -ltn" 2>/dev/null | grep -q "10.30.0.10:2404"; then ok "controller real listener 10.30.0.10:2404"; else no "controller real listener 10.30.0.10:2404" "start iec104_controller_decoy_service on controller"; fi
if ssh -o ConnectTimeout=6 decoy "ss -ltn" 2>/dev/null | grep -q "10.30.0.99:2404"; then ok "decoy listener 10.30.0.99:2404"; else no "decoy listener 10.30.0.99:2404" "start iec104_controller_decoy_service on decoy"; fi

echo "== collector operational API (10.50.0.20:9202) via defender =="
API="import urllib.request;print(urllib.request.urlopen('http://10.50.0.20:9202/operational-observations',timeout=8).read()[:60])"
if ssh -o ConnectTimeout=6 defender "python3 -c \"$API\"" >/dev/null 2>&1; then ok "collector operational API"; else no "collector operational API 10.50.0.20:9202" "start telemetry_collector_service on collector"; fi

echo "== gridsim plant service (10.40.0.20:8765) via controller =="
STATE="import urllib.request;print(urllib.request.urlopen('http://10.40.0.20:8765/state',timeout=6).read()[:60])"
if ssh -o ConnectTimeout=6 controller "python3 -c \"$STATE\"" >/dev/null 2>&1; then ok "gridsim plant /state"; else no "gridsim plant 10.40.0.20:8765" "start OpenDSS plant service on gridsim"; fi

echo "== service log files the driver tails =="
check_log(){ ssh -o ConnectTimeout=6 "$1" "test -f $2" 2>/dev/null && ok "log $1:$2" || no "log $1:$2" "service not started / path differs"; }
check_log controller '~/ecpomdg/multistage_live/logs/iec104_real_multistage_sensor_events.jsonl'
check_log controller '~/ecpomdg/iec104_controller_decoy/logs/iec104_real_controller_events.jsonl'
check_log decoy      '~/ecpomdg/multistage_live/logs/iec104_decoy_multistage_sensor_events.jsonl'
check_log collector  '~/ecpomdg/telemetry_ground_truth/logs/defender_operational_observation_events.jsonl'
check_log gridsim    '~/ecpomdg/t2_gridsim/logs/plant_service_events.jsonl'

echo
echo "SUMMARY: $PASS pass, $FAIL down"
[ "$FAIL" -eq 0 ] && echo "TESTBED READY -> run the live episode" || echo "TESTBED NOT READY -> start the DOWN services above, re-run preflight"
