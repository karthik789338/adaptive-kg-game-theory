# EC-POMDG: Knowledge-Guided Cyber Deception for IEC-104 Grid Control

This repository holds the code and results for EC-POMDG, a five-stage attacker-defender
game for cyber deception in power-grid industrial control systems. The defender does not
see the attacker's stage directly. It infers a belief over the five stages from IEC-104
traffic, using observation likelihoods conditioned on three knowledge graphs
(general cyber, ICS semantics, grid topology), and then decides when to arm a decoy,
redirect a control command, or contain the session.

The experiments are run in three settings: a self-contained simulator, the deployed
inference engine, and the SPHERE testbed with real IEC-104 controllers, an OpenDSS
IEEE-13 feeder, and a Neo4j knowledge graph.

For a longer walkthrough of the game and the results in plain language, see
`docs/EXPLAINER.md`.

## Results

**H1, belief-adaptive defense.** The belief-adaptive policy reaches 0.00 real-controller
compromise against both the cautious and the persistent attacker, against 18-81% for the
stage-blind policies. Its mean reward is +14.69 (cautious) and +2.51 (persistent).

**N1, deception-aware attacker.** We add an attacker that detects and evades a decoy when
it is armed on a fixed, early schedule. Under this attacker the greedy early-arming
policy's compromise rate rises from 0.18 to 0.86 (cautious) and from 0.65 to 0.95
(persistent). The belief-adaptive policy stays at 0.00, because it arms on evidence
rather than on a schedule and keeps containment as a fallback. This is run on the
deployed engine, which reproduces the base H1 table exactly in the no-evasion condition.

**N2, dynamic knowledge graph.** A static knowledge graph is fixed once and never
updated. The dynamic version keeps a per-campaign memory in Neo4j, so the belief filter
recognizes a returning attacker on the first turn instead of re-inferring it. On the live
Neo4j store the dynamic graph lowers log-loss by 0.19 to 0.24 over the static graph across
every paired episode. The advantage disappears when the attacker never returns, which
confirms it comes from recognizing repeat campaigns and not from anything else.

**N3, physics-aware deception.** We couple the game to an OpenDSS load flow and let the
defender spend its decoy budget on the DER buses whose voltage is most sensitive to a
malicious setpoint, which is where a rational attacker aims. On the IEEE-13 feeder this
cuts the voltage-violation rate by about half against a stage-blind defender at every
budget. On the official IEEE-123 feeder (91 DER buses) the same pattern holds and the gap
grows with budget: at budget 16 the physics-aware defender leaves 0.352 of attacks in
violation against 0.692 for random placement.

**Live SPHERE.** 160 episodes over real IEC-104 completed with no failures, and the decoy
redirect is visible on the wire. One result did not carry over from simulation: the
belief policy's lower spending on benign episodes did not appear live, where it armed as
often as the fixed policy. That points to the decision thresholds needing calibration on
live traffic, and is left as future work.

## Layout

```
.
├── experiments/             # self-contained experiments (Python stdlib; OpenDSS for N3)
│   ├── ecpomdg_standalone.py        # 5-stage game, fixed and deception-aware attacker
│   ├── n2_online_kg.py              # online vs static vs oracle KG inference
│   ├── n3_cyber_physical.py         # linear feeder sensitivity
│   ├── n3_opendss.py                # OpenDSS load flow, IEEE-13
│   ├── n3_ieee123.py                # OpenDSS load flow, IEEE-123 (scaling)
│   ├── get_ieee123_feeder.sh        # fetches the IEEE-123 feeder for n3_ieee123.py
│   ├── run_n1_authoritative.py      # N1 on the deployed ec_pomdg engine
│   ├── iec104_testbed.py            # the game over real IEC-104 frames on loopback
│   ├── stage_conditioned_policy.py, run_experiments_extended.py
│   ├── STAGE_CONDITIONED_ENGINE_PATCH.md
│   └── run_all_ec2.sh
├── sphere_engine/           # SPHERE deployment package
│   ├── pipeline/            # testbed bring-up, live H1, ablation, run_experiments.py
│   ├── scripts/             # offline H1/H2/replay/ablation runners
│   ├── src/ecpomdg_final/   # inference, KG, policy, simulator code
│   ├── kg_builders/         # the three knowledge-graph builders
│   ├── services/            # attacker, collector, controller/decoy
│   ├── sphere/, topology/, tests/, setup_patches/
│   └── RUNBOOK_SPHERE.md, SPHERE_PIPELINE.md, RUNBOOK_REPRODUCE.md
├── results/
│   ├── ec2/                 # simulator CSVs
│   └── sphere_live/         # testbed results (H1 live, KG ablation, N1 engine, IEEE-123)
└── docs/
    └── EXPLAINER.md
```

The five-stage game engine `ec_pomdg`, used by `sphere_engine/pipeline/run_experiments.py`
and `experiments/run_n1_authoritative.py`, is deployed on the SPHERE testbed. The
`ecpomdg_final` package in `sphere_engine/src` is the inference, KG, and policy code used
for the offline and live-KG experiments.

## Running the experiments

Simulator (any machine, Python stdlib; OpenDSS only for N3):

```bash
cd experiments
pip install --break-system-packages opendssdirect.py   # for n3_opendss.py and n3_ieee123.py
bash run_all_ec2.sh                                     # N1, N2, N3, OpenDSS, IEC-104
bash get_ieee123_feeder.sh && python3 n3_ieee123.py    # IEEE-123 scaling run
```

Deployed engine and live testbed: follow `sphere_engine/RUNBOOK_SPHERE.md` and
`sphere_engine/SPHERE_PIPELINE.md`. `experiments/run_n1_authoritative.py` reproduces the
N1 result on a node where the `ec_pomdg` package is importable; in the no-evasion
condition it returns the base H1 table.
