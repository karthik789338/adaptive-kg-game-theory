#!/usr/bin/env bash
# =============================================================================
# Deploy the EC-POMDG application stack onto a freshly materialized SPHERE
# testbed, using YOUR existing deploy scripts. Run on the XDC host (ka9d9).
#
# Prereq: your deploy scripts live under ~/ecpomdg_setup/<component>/ (restore
# them from your backup first -- see step 0). Each deploy_*.sh ssh-pushes code,
# builds the venv, writes the service, and starts it on the target nodes.
# =============================================================================
set -u
BACKUP="${BACKUP_DIR:-$HOME/backup_dir}"
SETUP="$HOME/ecpomdg_setup"

echo "== 0. restore the setup + runtime trees on the XDC host =="
if [ ! -d "$SETUP" ]; then
  [ -d "$BACKUP/ecpomdg_setup" ] || { echo "ERROR: $BACKUP/ecpomdg_setup not found; set BACKUP_DIR"; exit 1; }
  cp -r "$BACKUP/ecpomdg_setup" "$SETUP"
  [ -d "$BACKUP/ecpomdg" ] && cp -r "$BACKUP/ecpomdg" "$HOME/ecpomdg_pkg_src" || true
  echo "  restored ~/ecpomdg_setup"
else
  echo "  ~/ecpomdg_setup already present"
fi

run_deploy() {  # <component_dir> <script>
  local dir="$SETUP/$1" script="$2"
  echo; echo "############################################################"
  echo "## DEPLOY: $1/$script"
  echo "############################################################"
  if [ ! -f "$dir/$script" ]; then echo "  MISSING $dir/$script -- skipping"; return 1; fi
  ( cd "$dir" && bash "$script" ) || { echo "  >>> $script FAILED (paste output); stopping"; exit 2; }
}

# Dependency order: PLANT FIRST (the controller reads 10.40.0.20:8765 on startup),
# then endpoints -> telemetry -> attacker -> sensors -> defender stack.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo; echo "############################################################"
echo "## DEPLOY: gridsim plant service (step 0, before controller)"
echo "############################################################"
bash "$HERE/deploy_gridsim_plant.sh" || { echo "  >>> gridsim plant deploy FAILED; stopping"; exit 2; }

run_deploy iec104_controller_decoy        deploy_iec104_controller_decoy.sh
run_deploy telemetry_ground_truth         deploy_telemetry_ground_truth_pipeline.sh
run_deploy industroyer_inspired_iec104    deploy_industroyer_inspired_iec104_emulator.sh
run_deploy multistage_game                deploy_and_validate_decoy_live_multistage_sensor.sh
run_deploy multistage_game                deploy_and_validate_multistage_belief_runtime.sh
run_deploy multistage_game                deploy_and_validate_five_stage_ecpomdg_engine.sh
run_deploy kg_defender_integration        deploy_and_validate_live_kg_enriched_defender_observations.sh
run_deploy ecpomdg_runtime                deploy_and_validate_live_ecpomdg_runtime_bridge.sh

echo
echo "ALL DEPLOYS DONE -> verify with: bash pipeline/preflight_testbed.sh"
