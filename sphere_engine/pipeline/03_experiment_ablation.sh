#!/usr/bin/env bash
# =============================================================================
# Stage 03 - Experiment 2: 7-mask KG ablation using the testbed.
#  - KG feature tables are derived from the REAL Neo4j KGs (by namespace)
#  - the dynamic campaign store is the REAL Neo4j
#  - optionally runs a real-data inference check on telemetry collected by the
#    H1-live episodes (stage 02), adapted from the operational deltas
#
# Run on the defender node (through the Neo4j tunnel) or the kg node.
# Env: NEO4J_URI, NEO4J_PASSWORD  (set them to use the real graph; else synthetic)
# Arg 1 (optional): path to h1_live episode dirs for the real-data check.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
H1_EPISODES="${1:-$HOME/ecpomdg_audit/multistage_game/h1_live}"

echo "== 03.1 derive KG feature tables from the real Neo4j KGs =="
if [ -n "${NEO4J_PASSWORD:-}" ]; then
  python3 scripts/live/build_kg_tables.py || { echo "  (real-KG build failed; synthetic)"; python3 scripts/live/build_kg_tables.py --synthetic; }
else
  echo "  NEO4J_PASSWORD not set -> synthetic tables"; python3 scripts/live/build_kg_tables.py --synthetic
fi

echo "== 03.2 static 7-mask ablation (which KG helps per-event) =="
python3 scripts/run_experiment_ablation.py

echo "== 03.3 dynamic ablation (campaign memory in the real Neo4j) =="
python3 scripts/run_experiment_ablation.py --dynamic

echo "== 03.4 (optional) real-data inference check on collected H1-live telemetry =="
if [ -d "$H1_EPISODES" ]; then
  rm -rf data/realcheck
  python3 scripts/live/sphere_adapter.py --episodes-root "$H1_EPISODES" --out data/realcheck --population test --phase phase2 || true
  PYTHONPATH=src python3 - <<'PY' || true
import json, glob
from ecpomdg_final.dbn import CategoricalStageDBN
from ecpomdg_final.offline_kg import OfflineKG, EpisodeRuntimeGraph
from ecpomdg_final.simulator import featurize
from ecpomdg_final.metrics import stage_accuracy, mean
from ecpomdg_final.types import KnowledgeMode
SIX=["NORMAL","RECON","ACCESS","DER_ENUM","CONTROL","IMPACT"]; kg=OfflineKG(); eps=[]
for f in sorted(glob.glob('data/realcheck/test/phase2/*.ndjson')):
    evs=[json.loads(l) for l in open(f) if l.strip()]
    lab=json.load(open(f[:-7]+'.labels.json')); rt=EpisodeRuntimeGraph()
    eps.append([{"true_stage":s,"observation":featurize(e,kg,rt,KnowledgeMode.DYNAMIC_KG)} for e,s in zip(evs,lab['true_stages'])])
if eps:
    m=CategoricalStageDBN(KnowledgeMode.DYNAMIC_KG,stages=SIX).fit(eps); acc=[]
    for ep in eps:
        post=None
        for row in ep:
            post=m.update(post,row['observation']).posterior; acc.append(stage_accuracy(post,row['true_stage']))
    print(f"    real collected telemetry: {len(eps)} episodes, {sum(len(e) for e in eps)} events, acc={mean(acc):.2f} (wiring proof)")
else:
    print("    no adapted real episodes found (run stage 02 first to collect telemetry)")
PY
else
  echo "  no H1-live episode dir at $H1_EPISODES (run stage 02 first)"
fi
echo "STAGE 03 DONE -> results/kg_ablation.json , results/kg_ablation_dynamic.json"
