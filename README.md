# EC-POMDG — Evidence-Conditioned Partially-Observable Markov Deception Game

Knowledge-guided, game-theoretic cyber deception against multi-stage IEC-104 attacks
on a power-grid ICS testbed (NOMS). This repository holds the code and results for the
standalone experiments, the deployed engine, and the live SPHERE testbed run.

## Are the results supportive?

**Yes — the core claims hold, with one honest sim-to-real gap.** Belief-adaptive
defense beats stage-blind baselines; it is **uniquely robust to a deception-aware
attacker** (N1) — confirmed on the authoritative engine, where belief-adaptive keeps
**0.00 real-controller compromise** while a greedy early-arming policy collapses to
86–95%. The **dynamic knowledge graph beats static on recurring attackers** (N2),
confirmed on the real Neo4j store. **Physics-aware deception roughly halves voltage
violations** (N3), and the advantage **scales to the official IEEE-123 feeder**. The
one gap: the simulator's *cost-control* advantage for belief-adaptive did **not**
transfer to the live H1 run — a sim-to-real finding that motivates live threshold
calibration. A plain-language walkthrough is in [`docs/EXPLAINER.md`](docs/EXPLAINER.md).

### Headline numbers

| Result | Finding |
|---|---|
| H1 — belief-adaptive defense | 0.00 compromise both profiles vs **18–81%** for stage-blind; reward +14.69 / +2.51 |
| N1 — deception-aware attacker | belief-adaptive stays **0.00**; greedy early-arming collapses to **0.86 / 0.95** |
| N2 — dynamic KG | recognizes returning attacker at turn 0; live Neo4j −0.19..−0.24 log-loss, 100% of pairs |
| N3 — physics-aware (IEEE-13 / IEEE-123) | roughly halves voltage violations at every budget; advantage scales with feeder size |
| Live SPHERE | 160 real-IEC-104 episodes, 0 failures; real-Neo4j KG ablation |

## Repository layout

```
.
├── experiments/             # self-contained experiments (pure stdlib; OpenDSS for N3)
│   ├── ecpomdg_standalone.py        # N1: 5-stage game, fixed + deception-aware attacker
│   ├── n2_online_kg.py              # N2: online vs static vs oracle KG inference
│   ├── n3_cyber_physical.py         # N3: linear feeder sensitivity
│   ├── n3_opendss.py                # N3: real OpenDSS load flow (IEEE-13)
│   ├── n3_ieee123.py                # N3 scaling: official IEEE-123 feeder
│   ├── get_ieee123_feeder.sh        # fetches the IEEE-123 benchmark for n3_ieee123.py
│   ├── run_n1_authoritative.py      # N1 on the authoritative ec_pomdg engine
│   ├── iec104_testbed.py            # EC-POMDG over real IEC-104 frames (loopback)
│   ├── stage_conditioned_policy.py, run_experiments_extended.py
│   ├── STAGE_CONDITIONED_ENGINE_PATCH.md
│   └── run_all_ec2.sh               # one-shot runner
├── sphere_engine/           # SPHERE deployment package
│   ├── pipeline/            # 02_experiment_h1_live.py, 03_experiment_ablation.sh, run_experiments.py, ...
│   ├── scripts/            # run_experiment_{h1,h2,replay,ablation}.py, run_all_offline.py
│   ├── src/ecpomdg_final/   # game, dbn, policies, offline_kg, simulator, live/
│   ├── kg_builders/        # general_cyber, power_grid_ics, component_topology, neo4j_migration
│   ├── services/          # attacker, collector, controller_decoy
│   ├── sphere/, topology/, tests/, setup_patches/
│   └── RUNBOOK_SPHERE.md, SPHERE_PIPELINE.md, RUNBOOK_REPRODUCE.md
├── results/
│   ├── ec2/                # standalone CSVs (N1/N2/N3, iec104)
│   └── sphere_live/        # live testbed results (H1 live, KG ablation, N1-engine, IEEE-123)
└── docs/
    └── EXPLAINER.md         # plain-language walkthrough of the game and results
```

> The authoritative five-stage game engine (`ec_pomdg`, used by
> `sphere_engine/pipeline/run_experiments.py` and `experiments/run_n1_authoritative.py`)
> is deployed on the SPHERE testbed; the `ecpomdg_final` package in `sphere_engine/src`
> is the inference/KG/policy codebase used for the offline and live-KG experiments.

## Reproduce

### Standalone experiments (any machine, pure stdlib; OpenDSS optional)
```bash
cd experiments
pip install --break-system-packages opendssdirect.py   # for n3_opendss.py / n3_ieee123.py
bash run_all_ec2.sh                                     # N1, N2, N3, N3-OpenDSS, live IEC-104
bash get_ieee123_feeder.sh && python3 n3_ieee123.py    # N3 scaling on IEEE-123
```

### Deployed engine + live SPHERE
See `sphere_engine/RUNBOOK_SPHERE.md` and `sphere_engine/SPHERE_PIPELINE.md`.
The live result files are in `results/sphere_live/`. The N1-on-engine result is
reproduced with `experiments/run_n1_authoritative.py` on a node where the `ec_pomdg`
package is importable (it reproduces the base H1 table exactly in the fixed condition).

## Three tiers of evidence

| Tier | What | Where | Headline |
|---|---|---|---|
| A. Standalone | calibrated 5-stage engine, N1/N2/N3 | any machine | belief-adaptive 0 compromise; N1 robustness; N3 OpenDSS |
| B. Deployed engine | real inference/KG/policy code, synthetic traffic | EC2 / SPHERE XDC | belief-adaptive best utility; replay: dynamic ≫ static on recurring |
| C. Live SPHERE | real IEC-104 + OpenDSS gridsim + Neo4j | testbed | live H1 (0 failures) + real-Neo4j KG ablation + N1-on-engine |
