#!/usr/bin/env bash
# =============================================================================
# Stage 01 - start Neo4j on the kg node and load the 3 knowledge graphs.
# Run on the kg node (or via ssh kg). Produces the KGNode graph the experiments
# read, plus the inference schema the campaign memory uses.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
NEO4J_HOME="${NEO4J_HOME:-$HOME/ecpomdg/neo4j_community/neo4j-community-2026.09.0}"
: "${NEO4J_PASSWORD:?set NEO4J_PASSWORD}"

echo "== 01.1 make Neo4j listen on 0.0.0.0 (idempotent) =="
CONF="$NEO4J_HOME/conf/neo4j.conf"
cp "$CONF" "$CONF.bak.$(date +%s)" || true
sed -i '/server\.default_listen_address/d; /server\.bolt\.listen_address/d' "$CONF"
printf 'server.default_listen_address=0.0.0.0\nserver.bolt.listen_address=0.0.0.0:7687\n' >> "$CONF"
"$NEO4J_HOME/bin/neo4j-admin" server validate-config
"$NEO4J_HOME/bin/neo4j" restart
sleep 8
"$NEO4J_HOME/bin/cypher-shell" -a bolt://127.0.0.1:7687 -u neo4j -p "$NEO4J_PASSWORD" "RETURN 1;" >/dev/null
echo "  Neo4j up on 0.0.0.0:7687"

echo "== 01.2 build the three knowledge graphs =="
python3 kg_builders/component_topology/build_power_grid_component_topology_knowledge_graph.py
python3 kg_builders/power_grid_ics/build_power_grid_ics_cyber_knowledge_graph.py
python3 kg_builders/general_cyber/build_general_cyber_knowledge_graph.py

echo "== 01.3 load them into Neo4j (KGNode by kg_namespace) =="
NEO4J_URI=bolt://127.0.0.1:7687 NEO4J_PASSWORD="$NEO4J_PASSWORD" \
  python3 kg_builders/neo4j_migration/import_frozen_knowledge_graphs_into_neo4j.py

echo "== 01.4 initialise the inference schema (EventSemantic / AttackStage) =="
NEO4J_URI=bolt://127.0.0.1:7687 NEO4J_PASSWORD="$NEO4J_PASSWORD" \
  python3 scripts/initialize_neo4j_schema.py

echo "== 01.5 sanity: namespaces present =="
"$NEO4J_HOME/bin/cypher-shell" -a bolt://127.0.0.1:7687 -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n:KGNode) RETURN n.kg_namespace AS ns, count(*) AS c ORDER BY c DESC;"
echo "STAGE 01 DONE"
