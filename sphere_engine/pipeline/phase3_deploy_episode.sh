#!/usr/bin/env bash
# PHASE 3 (step 5) - deploy the phase3d2a live-episode code + the SELECT-only probe,
# run the non-destructive self-tests. Apply setup_patches first, then run on XDC.
set -u
C="${KG_HOST:-kg}"
D="$HOME/ecpomdg_setup/dynamic_knowledge_graph"
M="$HOME/ecpomdg_setup/multistage_game"

echo "== 1. XDC: compile + copy coordinator into multistage_game =="
python3 -m py_compile "$D/validate_phase3d2a_live_neo4j_predecision_integration.py" \
   "$D/ecpomdg_phase3d2a_online_kg_transport.py" "$D/ingest_and_query_phase3d2a_live_neo4j_observations.py" \
   && echo "   compile PASS"
cp "$D/validate_phase3d2a_live_neo4j_predecision_integration.py" "$M/" && echo "   coordinator -> multistage_game"

echo "== 2. XDC transport snapshot self-test (no network) =="
python3 "$D/ecpomdg_phase3d2a_online_kg_transport.py"

echo "== 3. ship phase3d2a overlay + worker to kg =="
ssh "$C" 'mkdir -p ~/ecpomdg_setup/dynamic_knowledge_graph ~/ecpomdg_audit/dynamic_knowledge_graph/online_ingestion'
scp -q "$D"/*.py   "$C:ecpomdg_setup/dynamic_knowledge_graph/"
scp -q "$D"/*.json "$C:ecpomdg_setup/dynamic_knowledge_graph/" 2>/dev/null || true
echo "   shipped"

echo "== 4. kg worker self-test (reads/writes NO Neo4j data) =="
ssh -tt "$C" '$HOME/ecpomdg/venvs/neo4j_kg_import/bin/python $HOME/ecpomdg_setup/dynamic_knowledge_graph/ingest_and_query_phase3d2a_live_neo4j_observations.py --self-test'

echo "== 5. deploy the SELECT-only probe to the attacker =="
scp -q "$M/iec104_real_select_only_probe.py" attacker:ecpomdg/industroyer_inspired_iec104/app/ \
  && ssh attacker 'python3 -m py_compile ~/ecpomdg/industroyer_inspired_iec104/app/iec104_real_select_only_probe.py && echo "PROBE_DEPLOY: PASS"'
