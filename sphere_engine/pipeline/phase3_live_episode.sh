#!/usr/bin/env bash
# PHASE 3 (step 6) - the live online-Neo4j NO_KG integration episode on SPHERE.
# Real observe + SELECT-only (never a real EXECUTE); synchronous Neo4j online
# commit+read BEFORE the defender decision; decoy gated by one-use auth; NO_KG
# first-run withholds control. Interactive: prompts for the Neo4j password on
# kg's TTY during the online commit. Do NOT pipe the output; do NOT use set -e.
#
# Expected tail: GRAPH_COMMIT_AND_READ_BEFORE_POLICY_DECISION: PASS,
# POST_SELECT_ACTION: MONITOR, MONITOR_WITHHELD_CONTROL: PASS,
# REAL_NO_EXECUTE: PASS, REAL_PLANT_STATE_UNCHANGED: PASS,
# OBSERVED_STATUS: CONTROL_WITHHELD_CENSORED, exit 0.
set +e
M="$HOME/ecpomdg_setup/multistage_game"
D="$HOME/ecpomdg_setup/dynamic_knowledge_graph"
PYTHONPATH="$HOME/ecpomdg:$M:$D" \
  python3 "$M/validate_phase3d2a_live_neo4j_predecision_integration.py" --mode NO_KG
printf 'LIVE_EPISODE_PROCESS_EXIT_CODE=%s\n' "$?"
