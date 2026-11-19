# EC-POMDG reproducible pipeline — testbed → Neo4j KG → 2 experiments

Four stages, in order. Stages 00–01 create the testbed and the knowledge graphs;
stage 02 is **Experiment 1 (H1 live)**; stage 03 is **Experiment 2 (KG ablation)**.

```
pipeline/00_create_testbed.sh      # materialize topology/sphere-testbed.py + install deps + start services
pipeline/01_neo4j_and_kg.sh        # start Neo4j (0.0.0.0) on kg, build + load the 3 KGs (KGNode)
pipeline/02_experiment_h1_live.py  # Experiment 1: 4 policies × {attack,benign} live episodes, aggregated
pipeline/03_experiment_ablation.sh # Experiment 2: 7-mask ablation (static+dynamic) over the real KGs/Neo4j
```

## Honest scope (read first)
- **Experiment 1 is live on the testbed** and uses your validated EC-POMDG engine
  (`MultiStageBeliefUpdater` + `BeliefConditionedMultiStageDefenderPolicy` +
  `UserSpaceActionGate`). The driver (`sphere/h1_live_episode.py`) is a faithful
  generalization of your `validate_live_action_gated_decoy_episode.py` — same ssh
  flow, same gate, same evidence matching — extended to the 4 policies, a benign
  path, and per-policy aggregation.
- **The real controller never executes, by design** (your safety invariant is kept:
  the driver aborts if it ever sees a real execute). So **physical-impact rate is
  not measured live**; H1 live measures **decoy-diversion rate, defender cost,
  wasted cost on benign episodes, and outcome category**. The physical-impact
  number stays the simulation result (`scripts/run_experiment_h1.py`), labeled.
- **Experiment 2** derives its static features from your **real Neo4j KGs** by
  namespace and uses the **real Neo4j** as the dynamic campaign store. The
  inference statistics run on the validated traffic model (real collected
  telemetry is too sparse for statistics; it is used as a wiring check).

## Stage 00 — create the testbed (XDC host)
```bash
export SPHERE_PROJECT=ecpomdg SPHERE_EXPERIMENT=ecpomdg-powergrid
bash pipeline/00_create_testbed.sh
# verify: ssh controller 'ss -ltn | grep 2404'  ;  ssh gridsim 'curl -s :8765/state'
```

## Stage 01 — Neo4j + the 3 KGs (kg node)
```bash
export NEO4J_PASSWORD=...        # rotate after the run
bash pipeline/01_neo4j_and_kg.sh
# prints KGNode counts per namespace (general_cyber / power_grid_ics / component_topology)
```

## Stage 02 — Experiment 1: H1 live (orchestration host)
Needs ssh to all nodes and your package path.
```bash
# validate the pipeline WITHOUT the testbed first:
python3 pipeline/02_experiment_h1_live.py --episodes 20 --mock

# then the real live run (each episode drives real IEC-104 through the gate):
PYTHONPATH="$HOME/ecpomdg:$HOME/ecpomdg_setup/multistage_game" \
  python3 pipeline/02_experiment_h1_live.py --episodes 20 --mode DYNAMIC_KG
# -> results/h1_live_results.json ; table of divert(atk) / cost(atk) / wasted(benign)
# episode captures land in ~/ecpomdg_audit/multistage_game/h1_live/
```
Expected shape: MONITOR_ONLY diverts nothing at zero cost; FIXED_SCHEDULE diverts
most but wastes cost on benign; BELIEF_ADAPTIVE matches FIXED's diversion while
wasting far less on benign — the H1 cost-control result, measured live.

## Stage 03 — Experiment 2: KG ablation (defender node, Neo4j tunnel)
```bash
export NEO4J_URI=bolt://127.0.0.1:7687 NEO4J_PASSWORD=...
bash pipeline/03_experiment_ablation.sh ~/ecpomdg_audit/multistage_game/h1_live
# -> results/kg_ablation.json (static 7-mask) , results/kg_ablation_dynamic.json
```

## Offline validation (no testbed)
```bash
python3 -m pytest -q tests
python3 pipeline/02_experiment_h1_live.py --episodes 40 --mock
python3 scripts/live/build_kg_tables.py --synthetic && python3 scripts/run_experiment_ablation.py
```

The inference / KG / policy code in `src/` and `scripts/` is unchanged and
independently tested; stages 02–03 wire it to your live stack and real Neo4j.
