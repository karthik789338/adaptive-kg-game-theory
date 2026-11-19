#!/usr/bin/env bash
# PHASE 3 (step 4) - build the 5 Topology<->ICS semantic bridges in Neo4j
# (the 3D.1C overlay = the mechanism by which attack behaviors are anchored to
# the KG). manage_phase3d1c is the freeze-repinned build: its live-core guard is
# relaxed from == 6742/33630 to >= (the active-only graph is a superset of the
# original frozen core; general_cyber drifted and carries no bridges). The 5
# bridges are new nodes OUTSIDE :KGNode, so the frozen core is unchanged
# (before == after). Manifest + attestation are the unchanged original-baseline
# provenance. Apply setup_patches first, then run on the XDC host.
set -u
C="${KG_HOST:-kg}"
D="$HOME/ecpomdg_setup/dynamic_knowledge_graph"
A_ATT="$HOME/ecpomdg_audit/dynamic_knowledge_graph/phase3d1c_calibration_evidence_attestation.json"

echo "== 0. sanity: manage_phase3d1c is freeze-repinned (>= not ==) =="
grep -q "Frozen node count below original" "$D/manage_phase3d1c_neo4j_semantic_bridges.py" \
  || { echo ">>> manage_phase3d1c not repinned; apply setup_patches"; exit 1; }

echo "== 1. ship manager + manifest + attestation to kg =="
ssh "$C" "mkdir -p ~/ecpomdg_setup/dynamic_knowledge_graph"
scp -q "$D/manage_phase3d1c_neo4j_semantic_bridges.py" "$C:ecpomdg_setup/dynamic_knowledge_graph/"
scp -q "$D/phase3d1c_semantic_bridge_manifest.json"   "$C:ecpomdg_setup/dynamic_knowledge_graph/"
scp -q "$A_ATT" "$C:ecpomdg_setup/dynamic_knowledge_graph/"
echo "    shipped"

echo "== 2. dry-run -> apply(5 bridges) -> verify  (ONE Neo4j password prompt) =="
ssh -tt "$C" 'PY="$HOME/ecpomdg/venvs/neo4j_kg_import/bin/python";
S="$HOME/ecpomdg_setup/dynamic_knowledge_graph/manage_phase3d1c_neo4j_semantic_bridges.py";
read -s -p "Neo4j password: " NEO4J_PASSWORD; echo; export NEO4J_PASSWORD;
"$PY" "$S" --dry-run && \
EC_POMDG_BRIDGE_APPLY=YES "$PY" "$S" --apply && \
"$PY" "$S" --verify'
