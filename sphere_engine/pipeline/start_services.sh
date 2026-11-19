#!/usr/bin/env bash
# =============================================================================
# Bring up the SPHERE services the live H1 episode needs. Run on the XDC host
# (ssh to all nodes). Uses your deployed start scripts under ~/ecpomdg/...
#
# CONFIRMED from your backup:
#   - iec104 endpoints:  iec104_controller_decoy/start_iec104_endpoint_service.sh {real|decoy}
#   - collector:         telemetry_ground_truth/start_telemetry_collector_service.sh
#   - forwarders:        telemetry_ground_truth/start_iec104_telemetry_forwarder.sh {real_controller|decoy_controller}
# TODO (confirm the exact deployed names via the discovery command, then fill in):
#   - gridsim plant service on 10.40.0.20:8765
#   - multistage sensor service on controller + decoy (produces *_multistage_sensor_events.jsonl)
# =============================================================================
set -u
run(){ echo "+ ssh $1 $2"; ssh -o ConnectTimeout=8 "$1" "$2" || echo "  (FAILED on $1 -- check path)"; }

echo "== 1. gridsim plant service (10.40.0.20:8765) =="
run gridsim 'bash ~/ecpomdg/t2_gridsim/app/start_gridsim_plant.sh'

echo "== 2. IEC-104 endpoints =="
run controller 'bash ~/ecpomdg/iec104_controller_decoy/start_iec104_endpoint_service.sh real'
run decoy      'bash ~/ecpomdg/iec104_controller_decoy/start_iec104_endpoint_service.sh decoy'

echo "== 3. multistage sensor services (produce *_multistage_sensor_events.jsonl) =="
# run controller 'bash ~/ecpomdg/multistage_live/<START_OR_SWITCH>.sh real'   # <-- fill from discovery
# run decoy      'bash ~/ecpomdg/multistage_live/<START_OR_SWITCH>.sh decoy'  # <-- fill from discovery
echo "  TODO: start/switch your multistage sensor services here"

echo "== 4. telemetry collector + forwarders =="
run collector  'bash ~/ecpomdg/telemetry_ground_truth/start_telemetry_collector_service.sh'
run controller 'bash ~/ecpomdg/telemetry_ground_truth/start_iec104_telemetry_forwarder.sh real_controller'
run decoy      'bash ~/ecpomdg/telemetry_ground_truth/start_iec104_telemetry_forwarder.sh decoy_controller'

echo
echo "Now re-run: bash pipeline/preflight_testbed.sh"
