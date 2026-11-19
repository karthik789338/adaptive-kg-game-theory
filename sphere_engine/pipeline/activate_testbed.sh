#!/usr/bin/env bash
# =============================================================================
# Activate the SPHERE testbed services idempotently. Safe to re-run: every
# service is checked first and only (re)started if down, so this never hits the
# non-idempotent "already switched" collisions.
#
# NOTE: the H1/H2 experiments (pipeline/run_experiments.py) run on the deployed
# ec_pomdg engine and DO NOT need any of these services. This script is for the
# live-attack path only.
#
# Run on the XDC host (ssh to all nodes).
# =============================================================================
set -u
up(){ echo "  UP    $1"; }
start(){ echo "  START $1"; }
skip(){ echo "  SKIP  $1"; }

echo "== gridsim plant (10.40.0.20:8765) =="
if ssh -o ConnectTimeout=6 controller "python3 -c \"import urllib.request;urllib.request.urlopen('http://10.40.0.20:8765/state',timeout=4)\"" 2>/dev/null; then
  up "plant /state"
else
  start "plant"; ssh gridsim 'bash ~/ecpomdg/t2_gridsim/app/start_gridsim_plant.sh' || echo "    (plant start failed)"
fi

echo "== IEC-104 endpoints (:2404) =="
for pair in "controller:10.30.0.10:real" "decoy:10.30.0.99:decoy"; do
  host="${pair%%:*}"; rest="${pair#*:}"; ip="${rest%%:*}"; mode="${rest##*:}"
  if ssh -o ConnectTimeout=6 "$host" "ss -ltn" 2>/dev/null | grep -q "$ip:2404"; then
    up "$host $ip:2404"
  else
    start "$host $mode endpoint"
    ssh "$host" "bash ~/ecpomdg/iec104_controller_decoy/start_iec104_endpoint_service.sh $mode" || echo "    (failed)"
  fi
done

echo "== telemetry collector (10.50.0.20:9202) + forwarders =="
if ssh -o ConnectTimeout=6 defender "python3 -c \"import urllib.request;urllib.request.urlopen('http://10.50.0.20:9202/health',timeout=4)\"" 2>/dev/null \
   || ssh -o ConnectTimeout=6 collector "ss -ltn" 2>/dev/null | grep -q "10.50.0.20:9202"; then
  up "collector 9202"
else
  start "collector"
  ssh collector 'bash ~/ecpomdg/telemetry_ground_truth/start_telemetry_collector_service.sh' || echo "    (failed)"
fi
ssh controller 'bash ~/ecpomdg/telemetry_ground_truth/start_iec104_telemetry_forwarder.sh real_controller'  >/dev/null 2>&1 && up "real forwarder"  || skip "real forwarder"
ssh decoy      'bash ~/ecpomdg/telemetry_ground_truth/start_iec104_telemetry_forwarder.sh decoy_controller' >/dev/null 2>&1 && up "decoy forwarder" || skip "decoy forwarder"

echo "== decoy multi-stage sensor =="
if ssh -o ConnectTimeout=6 decoy "test -f ~/ecpomdg/multistage_live/logs/iec104_decoy_multistage_sensor_events.jsonl" 2>/dev/null; then
  up "decoy multistage sensor (already switched)"
else
  skip "decoy multistage sensor -> run the decoy sensor deploy step once"
fi

echo
echo "== KG-dependent services (NOT required for H1/H2 experiments) =="
skip "defender operational observations + kg_defender enrichment"
echo "       These need the three frozen knowledge-graph files (raw node/edge"
echo "       data), which were absent on this rebuilt testbed. The engine"
echo "       experiments do not use them. To restore: place the frozen KGs on"
echo "       the kg node, run neo4j_knowledge_graph_migration + "
echo "       kg_defender_integration/build_unified_defender_knowledge_index.sh."
echo
echo "Run the experiments now (no services required):"
echo "  PYTHONPATH=\"\$HOME/ecpomdg\" python3 ecpomdg_sphere/pipeline/run_experiments.py --seeds 200"
