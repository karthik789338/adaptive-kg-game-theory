#!/usr/bin/env bash
# =============================================================================
# PHASE 1 - regenerate the three knowledge graphs and load Neo4j.
#
# The raw KG node/edge .jsonl were not in the backup, so we rebuild them from
# authoritative sources. The per-KG build scripts are self-contained: they ssh
# to the kg node, DOWNLOAD the public datasets there, stage the project-specific
# sources inline, build, validate, and freeze sha256. This runner sequences
# them, then imports all three into live Neo4j and renders the KG visuals.
#
# Run on the XDC host (ssh to kg + gridsim). Prereq: ~/ecpomdg_setup restored
# (deploy_all.sh step 0 does this), and the kg node has outbound HTTPS to
# GitHub, capec.mitre.org, cwe.mitre.org, and www.cisa.gov.
#
# NOTE: CISA KEV updates daily, so the rebuilt general-cyber KG will NOT match
# the original frozen sha256 -- it is re-frozen with fresh hashes here. It is
# functionally equivalent (same structure/semantics), which is what the
# experiments need.
# =============================================================================
set -u
SETUP="$HOME/ecpomdg_setup"

run(){  # <component_dir> <script>
  echo; echo "############################################################"
  echo "## $1/$2"
  echo "############################################################"
  local d="$SETUP/$1"
  [ -f "$d/$2" ] || { echo "  MISSING $d/$2"; exit 1; }
  ( cd "$d" && bash "$2" ) || { echo "  >>> $2 FAILED; stopping"; exit 2; }
}

echo "== 0. source reachability preflight (on the kg node) =="
ssh -o ConnectTimeout=8 kg 'bash -s' <<'REMOTE'
set -u
check(){ code=$(curl -s -o /dev/null -w "%{http_code}" -I --max-time 20 "$2" 2>/dev/null);
  case "$code" in 200|301|302) echo "  PASS  $1 ($code)";; *) echo "  DOWN  $1 ($code) -> $2";; esac; }
check "MITRE ATT&CK Enterprise" "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack-19.2.json"
check "MITRE ATT&CK ICS"        "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/ics-attack/ics-attack-19.2.json"
check "CAPEC 3.9"               "https://capec.mitre.org/data/xml/capec_v3.9.xml"
check "CWE 4.20"                "https://cwe.mitre.org/data/xml/cwec_v4.20.xml.zip"
check "CISA KEV"                "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
REMOTE
echo "  (If any are DOWN, the kg node can't reach that source -- fix egress or"
echo "   stage that file manually before continuing. component_topology needs no download.)"
echo
read -r -p "Proceed with the build? [y/N] " ans
case "$ans" in y|Y) ;; *) echo "stopped."; exit 0;; esac

echo
echo "== 0.5 prepare the shared KG builder venv on the kg node =="
# The per-KG scripts assume ~/ecpomdg/venvs/knowledge_graphs exists; create it
# once here so the build order (topology first, no download) doesn't matter.
ssh -o ConnectTimeout=12 kg 'bash -s' <<'REMOTE'
set -euo pipefail
VENV="$HOME/ecpomdg/venvs/knowledge_graphs"
UV="$HOME/.local/bin/uv"
mkdir -p "$HOME/.local/bin" "$HOME/ecpomdg/venvs"
if [ ! -x "$UV" ]; then
  curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/0.12.23/install.sh | env UV_NO_MODIFY_PATH=1 sh
fi
if [ ! -x "$VENV/bin/python" ]; then
  "$UV" venv --python /usr/bin/python3 "$VENV"
fi
"$UV" pip install --python "$VENV/bin/python" "networkx==3.7"
"$VENV/bin/python" -c "import networkx; print('KG_VENV_READY networkx', networkx.__version__)"
REMOTE
[ $? -eq 0 ] || { echo "  >>> KG venv prep FAILED; stopping"; exit 2; }

# 1-3. build the three KGs (each downloads its sources + freezes on the kg node)
run power_grid_component_topology_knowledge_graph  build_power_grid_component_topology_knowledge_graph.sh
run power_grid_ics_cyber_knowledge_graph           build_power_grid_ics_cyber_knowledge_graph.sh
run general_cyber_knowledge_graph                  build_general_cyber_knowledge_graph.sh

# 4. import all three frozen KGs into live Neo4j on the kg node
run neo4j_knowledge_graph_migration                deploy_and_import_three_frozen_knowledge_graphs.sh

# 5. KG visualizations ("images for semantics")
run kg_visualizations                              deploy_all_knowledge_graph_visualizations.sh

echo
echo "================================================================"
echo "PHASE 1 COMPLETE -> three KGs built, frozen, and imported to Neo4j."
echo "Next: Phase 2 (kg_defender index + live-KG experiments). Verify with:"
echo "  ssh kg 'ss -ltn | grep 7687'   # Neo4j bolt should be UP"
echo "================================================================"
