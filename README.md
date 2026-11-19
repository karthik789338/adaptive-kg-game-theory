# EC-POMDG — Evidence-Conditioned Partially-Observable Markov Deception Game

Knowledge-guided, game-theoretic cyber deception against multi-stage IEC-104 attacks
on a power-grid ICS testbed (NOMS 2027). This repository holds all code and results
for the standalone experiments, the deployed engine, and the live SPHERE testbed run.

## Are the results supportive?

**Yes — the core claims hold, with one honest sim-to-real gap.** Belief-adaptive
defense beats stage-blind baselines; it is **uniquely robust to a deception-aware
attacker** that collapses every baseline (N1); the **dynamic knowledge graph beats
static on recurring attackers** (N2), confirmed on the real Neo4j store; and
**physics-aware deception roughly halves voltage violations** (N3). The one gap: the
simulator's *cost-control* advantage for belief-adaptive did **not** transfer to the
live H1 run — a sim-to-real finding that strengthens the paper and motivates live
threshold calibration. Full breakdown in [`docs/RESULTS.md`](docs/RESULTS.md);
novelty in [`docs/NOVELTY.md`](docs/NOVELTY.md).

## Repository layout

```
ecpomdg-noms/
├── standalone_experiments/   # self-contained (EC2), pure stdlib — N1/N2/N3
│   ├── ecpomdg_standalone.py     # N1: 5-stage game, fixed + deception-aware attacker
│   ├── n2_online_kg.py           # N2: online vs static vs oracle KG inference
│   ├── n3_cyber_physical.py      # N3: linear feeder sensitivity
│   ├── n3_opendss.py             # N3: real OpenDSS load-flow coupling
│   ├── iec104_testbed.py         # EC-POMDG over real IEC-104 frames (loopback)
│   ├── stage_conditioned_policy.py, run_experiments_extended.py  # ec_pomdg drop-ins
│   ├── STAGE_CONDITIONED_ENGINE_PATCH.md
│   └── run_all_ec2.sh            # one-shot runner
├── sphere_engine/            # full SPHERE deployment package (ecpomdg_final)
│   ├── pipeline/ 02_experiment_h1_live.py, 03_experiment_ablation.sh, ...
│   ├── scripts/ run_experiment_{h1,h2,replay,ablation}.py, run_all_offline.py
│   ├── src/ecpomdg_final/        # game, dbn, policies, offline_kg, simulator, live/
│   ├── kg_builders/, services/, topology/, tests/
│   └── RESULTS.md, RUNBOOK_SPHERE.md, SPHERE_PIPELINE.md
├── results/
│   ├── ec2/                  # full-scale standalone CSVs (N1/N2/N3/iec104)
│   ├── engine_offline/       # deployed-engine committed RESULTS.md
│   └── sphere_live/          # live testbed results (+ DOWNLOAD_FROM_SPHERE.md)
├── docs/
│   ├── RESULTS.md            # all tiers, every number, "supportive?" verdict
│   ├── NOVELTY.md            # contributions vs related work (answers "novelty missing")
│   └── EC-POMDG_GAME_EXPLAINED.md   # full plain-language explainer of the game
├── game_tree/
│   ├── EC-POMDG_game_tree.drawio                     # editable, deployed game (reference style)
│   ├── EC-POMDG_game_tree_preview.png                # preview of the above
│   ├── EC-POMDG_game_tree_updated.{png,svg,drawio}   # stage-conditioned extension view
│   └── EC-POMDG_game_tree_base_from_code.drawio      # prior base-game tree
└── paper/ec_pomdg_noms_current.tex   # current submission (updated later, per-section)
```

## Reproduce

### Tier A — standalone (EC2 / any machine, pure stdlib; OpenDSS optional)
```bash
cd standalone_experiments
pip install --break-system-packages opendssdirect.py   # only for n3_opendss.py
bash run_all_ec2.sh                                     # N1, N2, N3, N3-OpenDSS, live IEC-104
```

### Tier B/C — deployed engine + live SPHERE
See `sphere_engine/RUNBOOK_SPHERE.md` and `sphere_engine/SPHERE_PIPELINE.md`.
The live result files from the 2026-11-17 run are in `results/sphere_live/`; pull the
authoritative originals from the XDC per `results/sphere_live/DOWNLOAD_FROM_SPHERE.md`.

## Three tiers of evidence

| Tier | What | Where | Headline |
|---|---|---|---|
| A. Standalone | calibrated 5-stage engine, N1/N2/N3 | EC2 | belief-adaptive 0 compromise; N1 robustness; N3 OpenDSS |
| B. Deployed engine | real inference/KG/policy code, synthetic traffic | EC2/XDC | belief-adaptive best utility; replay: dynamic≫static on recurring |
| C. Live SPHERE | real IEC-104 + OpenDSS gridsim + Neo4j | testbed | live H1 (0 failures) + real-Neo4j KG ablation + sim-to-real gap |

## Notes
- The live Neo4j password was reset to `Karthik@789` during the 2026-11-17 run (rotate as desired).
- The paper's existing KG-ablation / H2 tables come from an earlier run; `docs/RESULTS.md`
  flags the reconciliation (use the live-Neo4j ablation + engine replay for consistency).
