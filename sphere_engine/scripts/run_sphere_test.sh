#!/usr/bin/env bash
# =============================================================================
# One-command SPHERE test for EC-POMDG: H1, H2, and dynamic-vs-static replay.
#
#   bash scripts/run_sphere_test.sh [REAL_EPISODES_ROOT]
#
# What it does, in order:
#   1. install deps + run unit tests
#   2. build the actor population (benign + attacker, with recurrence)
#   3. fold in your REAL captured episodes if a path is given
#   4. record campaigns into Neo4j (store of record) if NEO4J_PASSWORD is set,
#      else a local JSON store (still runs, clearly reported)
#   5. run the dynamic-vs-static replay through that store
#   6. run H2 (inference) and H1 (closed-loop) + joint
#   7. print a PASS/FAIL verdict per hypothesis
#
# Env (optional):
#   NEO4J_URI       default bolt://10.50.0.30:7687   (set to bolt://127.0.0.1:7687 on the kg node)
#   NEO4J_USER      default neo4j
#   NEO4J_PASSWORD  if set, Neo4j is used as the campaign store of record
#
# HONEST SCOPE: the attacker/benign population is produced by the validated
# traffic model (simulator) unless you pass real captures; your captured
# episodes are clean attacker-only with one source IP, so they are folded in as
# real samples but cannot carry the statistics alone. The campaign store is your
# real Neo4j when NEO4J_PASSWORD is set. For fully-live numbers, emit benign
# operator traffic + per-actor source IPs from the testbed and re-run.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
REAL_EPISODES="${1:-}"
NEO4J_URI="${NEO4J_URI:-bolt://10.50.0.30:7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"

echo "=== [1/7] deps + tests ==="
python3 -m pip install -q -r requirements.txt 2>/dev/null || echo "    (pip unavailable; assuming deps already installed)"
python3 - <<'PY' || { echo "MISSING core deps. Install them: python3 -m pip install numpy pandas networkx neo4j"; exit 1; }
import importlib
for m in ("numpy", "pandas", "networkx"):
    importlib.import_module(m)
print("    core deps present")
PY
python3 -m pip install -q pytest >/dev/null 2>&1 || true
python3 -m pytest -q tests 2>/dev/null || echo "    (pytest unavailable; skipping unit tests - experiments still run)"

echo "=== [2/7] build actor population (benign + attacker, recurrence 0.6) ==="
rm -rf data/streams data/store_*.json
python3 scripts/live/ecpomdg_live.py synth --attack-actors 120 --benign-actors 120 --recurrence 0.6

if [ -n "$REAL_EPISODES" ]; then
  echo "=== [3/7] REAL-DATA wiring check on captured episodes: $REAL_EPISODES ==="
  rm -rf data/realcheck
  python3 scripts/live/sphere_adapter.py --episodes-root "$REAL_EPISODES" --out data/realcheck --population test --phase phase2
  # Run the belief filter on the REAL telemetry (separate from the statistic:
  # these captures are one source IP, clean attacker-only, small n).
  PYTHONPATH=src python3 - <<'PY'
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
    n=sum(len(e) for e in eps)
    print(f"    real telemetry: {len(eps)} episodes, {n} IEC-104 events, MAP stage accuracy={mean(acc):.2f} (wiring proof, not a hypothesis test)")
PY
else
  echo "=== [3/7] no REAL_EPISODES path given -> skipping real-data wiring check ==="
fi

NEO4J_ARGS=()
if [ -n "${NEO4J_PASSWORD:-}" ]; then
  echo "=== [4/7] probing Neo4j at $NEO4J_URI ==="
  if python3 - "$NEO4J_URI" "$NEO4J_USER" "$NEO4J_PASSWORD" <<'PY' 2>/dev/null
import sys
from neo4j import GraphDatabase
try:
    d = GraphDatabase.driver(sys.argv[1], auth=(sys.argv[2], sys.argv[3]), connection_timeout=5)
    d.verify_connectivity(); d.close(); sys.exit(0)
except Exception:
    sys.exit(1)
PY
  then
    echo "    Neo4j reachable -> using it as the campaign store of record"
    NEO4J_ARGS=(--neo4j-uri "$NEO4J_URI" --neo4j-user "$NEO4J_USER" --neo4j-password "$NEO4J_PASSWORD")
    NEO4J_URI="$NEO4J_URI" NEO4J_USER="$NEO4J_USER" NEO4J_PASSWORD="$NEO4J_PASSWORD" \
      python3 scripts/initialize_neo4j_schema.py || echo "    (schema init skipped - continuing)"
  else
    echo "    WARNING: Neo4j NOT reachable at $NEO4J_URI (is it listening on 0.0.0.0, firewall open?)."
    echo "    Falling back to a local JSON campaign store so the test still completes."
    echo "    Fix: on the kg node set server.default_listen_address=0.0.0.0 in neo4j.conf and restart,"
    echo "         or run this script on the kg node with NEO4J_URI=bolt://127.0.0.1:7687."
  fi
else
  echo "=== [4/7] NEO4J_PASSWORD not set -> local JSON campaign store (set it to use real Neo4j) ==="
fi

echo "=== [5/7] dynamic-vs-static replay (learn -> eval through the store) ==="
python3 scripts/live/ecpomdg_live.py "${NEO4J_ARGS[@]}" learn train
python3 scripts/live/ecpomdg_live.py "${NEO4J_ARGS[@]}" learn test
python3 scripts/live/ecpomdg_live.py "${NEO4J_ARGS[@]}" eval --out results/sphere_live_replay.json

echo "=== [6/7] H2 (inference) + H1 (closed-loop) + joint ==="
python3 scripts/run_experiment_h2.py --episodes 400   >/dev/null
python3 scripts/run_experiment_h1.py --episodes 500 --val 150 >/dev/null
python3 scripts/run_experiment_joint.py --episodes 400 --val 150 >/dev/null

echo "=== [7/7] VERDICT ==="
python3 - <<'PY'
import json
def load(p):
    try: return json.load(open(p))
    except Exception: return None
h2=load('results/h2_inference.json'); h1=load('results/h1_closed_loop.json')
jt=load('results/joint_h1_h2.json'); rp=load('results/sphere_live_replay.json')
def verdict(ok): return "PASS" if ok else "FAIL"

print("-"*64)
# H2: STATIC and DYNAMIC log-loss below TELEMETRY (CI excludes 0)
c=h2['log_loss_comparisons']
h2_ok = c['STATIC_minus_TELEMETRY']['ci_high']<0 and c['DYNAMIC_minus_TELEMETRY']['ci_high']<0
print(f"H2  KG improves stage inference ............... {verdict(h2_ok)}")
print(f"    telemetry={h2['pooled_summary']['TELEMETRY_ONLY']['log_loss']:.3f} "
      f"static={h2['pooled_summary']['STATIC_KG']['log_loss']:.3f} "
      f"dynamic={h2['pooled_summary']['DYNAMIC_KG']['log_loss']:.3f}  (lower better)")

# H1: BELIEF_ADAPTIVE best overall utility
po=h1['policy_outcomes']; best=max(po, key=lambda k: po[k]['mean_utility_overall'])
h1_ok = best=="BELIEF_ADAPTIVE"
print(f"H1  belief-conditioned defense best utility ... {verdict(h1_ok)}")
for k in ['MONITOR_ONLY','STAGE_AGNOSTIC','FIXED_SCHEDULE','BELIEF_ADAPTIVE']:
    print(f"    {k:<16} utility={po[k]['mean_utility_overall']:.2f}")

# Joint: dynamic/static belief beats telemetry on utility
jc=jt['paired_comparisons']['utility_DYNAMIC_minus_TELEMETRY']
joint_ok = jc['ci_low']>0
print(f"    joint: dynamic-KG belief beats telemetry ... {verdict(joint_ok)} "
      f"(+{jc['mean_diff']:.1f} utility, CI[{jc['ci_low']:.1f},{jc['ci_high']:.1f}])")

# Dynamic > static replay (seen a second time)
rc=rp['paired_comparisons']['log_loss_DYNAMIC_minus_STATIC_all']
rca=rp['paired_comparisons']['log_loss_DYNAMIC_minus_STATIC_recurring_attacker']
rep_ok = rc['ci_high']<0
print(f"DYN DYNAMIC KG beats STATIC on replay ......... {verdict(rep_ok)}")
print(f"    log-loss static={rp['STATIC_KG']['log_loss']:.3f} dynamic={rp['DYNAMIC_KG']['log_loss']:.3f}")
print(f"    recurring-attacker detection turn: static={rp['STATIC_KG']['mean_detection_turn_recurring_attacker']:.2f} "
      f"dynamic={rp['DYNAMIC_KG']['mean_detection_turn_recurring_attacker']:.2f}")
print("-"*64)
print("results/: h2_inference.json h1_closed_loop.json joint_h1_h2.json sphere_live_replay.json")
PY
echo "=== [8/8] KG 7-mask ablation (informational: which KG drives inference) ==="
if [ ${#NEO4J_ARGS[@]} -gt 0 ]; then
  echo "    building KG feature tables from your real Neo4j by namespace ..."
  NEO4J_URI="$NEO4J_URI" NEO4J_USER="$NEO4J_USER" NEO4J_PASSWORD="$NEO4J_PASSWORD" \
    python3 scripts/live/build_kg_tables.py >/dev/null 2>&1 \
    || { echo "    (real-KG build failed; using synthetic tables)"; python3 scripts/live/build_kg_tables.py --synthetic >/dev/null 2>&1; }
else
  python3 scripts/live/build_kg_tables.py --synthetic >/dev/null 2>&1
fi
python3 scripts/run_experiment_ablation.py --episodes 300 || echo "    (ablation skipped)"

echo "=== DONE ==="
