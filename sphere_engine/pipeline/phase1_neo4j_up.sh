#!/usr/bin/env bash
# =============================================================================
# PHASE 1 (final) - start Neo4j non-interactively and import the 3 KGs.
# Replaces the interactive initialize_and_start + migration prompts.
#
# Prereq: install_neo4j_community_on_kg.sh + repair_neo4j_duplicate_configuration.sh
# already ran (Java 21 + Neo4j installed, conf validates). The patched importer
# (env password + dynamic totals) is at
#   ~/ecpomdg_setup/neo4j_knowledge_graph_migration/import_frozen_knowledge_graphs_into_neo4j.py
#
# Usage (on the XDC host):
#   export NEO4J_PASSWORD='choose-a-strong-one-min-12-chars'
#   bash phase1_neo4j_up.sh
# =============================================================================
set -u
: "${NEO4J_PASSWORD:?set NEO4J_PASSWORD first (min 12 chars), then re-run}"
KG="${KG_HOST:-kg}"
IMPORTER="$HOME/ecpomdg_setup/neo4j_knowledge_graph_migration/import_frozen_knowledge_graphs_into_neo4j.py"
[ -f "$IMPORTER" ] || { echo "ERROR: importer not found at $IMPORTER"; exit 1; }

echo "== 1. set initial password (idempotent) + start Neo4j + wait for bolt =="
ssh "$KG" "NEO4J_PASSWORD='$NEO4J_PASSWORD' bash -s" <<'REMOTE'
set -euo pipefail
ROOT="$HOME/ecpomdg/neo4j_community"
NEO4J_HOME="$ROOT/neo4j-community-2026.09.0"
export JAVA_HOME="$ROOT/java21"; export PATH="$JAVA_HOME/bin:$PATH"
MARKER="$ROOT/.initial_password_configured"
if [ ! -f "$MARKER" ]; then
  "$NEO4J_HOME/bin/neo4j-admin" dbms set-initial-password "$NEO4J_PASSWORD" >/dev/null
  touch "$MARKER"; chmod 600 "$MARKER"
  echo "  INITIAL_PASSWORD_SET"
else
  echo "  password marker present (using existing password)"
fi
if "$NEO4J_HOME/bin/neo4j" status >/dev/null 2>&1; then
  echo "  neo4j already running"
else
  "$NEO4J_HOME/bin/neo4j" start
fi
for i in $(seq 1 60); do
  ss -ltn | grep -Fq '127.0.0.1:7687' && break
  sleep 2
done
if ss -ltn | grep -Fq '127.0.0.1:7687'; then
  echo "  NEO4J_BOLT_UP 127.0.0.1:7687"
else
  echo "  BOLT_NOT_UP -- last log lines:"; tail -n 40 "$NEO4J_HOME/logs/neo4j.log" 2>/dev/null || true
  exit 1
fi
REMOTE
[ $? -eq 0 ] || { echo ">>> Neo4j did not come up; stopping"; exit 1; }

echo "== 2. deploy patched importer to kg =="
ssh "$KG" 'mkdir -p ~/ecpomdg/neo4j_knowledge_graph_migration/app ~/ecpomdg/neo4j_knowledge_graph_migration/results ~/ecpomdg/neo4j_knowledge_graph_migration/audit'
scp -q "$IMPORTER" "$KG:~/ecpomdg/neo4j_knowledge_graph_migration/app/import_frozen_knowledge_graphs_into_neo4j.py"

echo "== 3. import the three KGs (non-interactive) =="
ssh "$KG" "NEO4J_PASSWORD='$NEO4J_PASSWORD' ~/ecpomdg/venvs/neo4j_kg_import/bin/python -u ~/ecpomdg/neo4j_knowledge_graph_migration/app/import_frozen_knowledge_graphs_into_neo4j.py"
rc=$?
echo
if [ "$rc" -eq 0 ]; then
  echo "================================================================"
  echo "PHASE 1 COMPLETE -> Neo4j up on 127.0.0.1:7687 with all 3 KGs imported."
  echo "Verify:  ssh $KG 'ss -ltn | grep 7687'"
  echo "================================================================"
else
  echo ">>> import FAILED (rc=$rc) -- paste the output above"
fi
exit "$rc"
