# EC-POMDG Final Experimental Codebase

This directory is the clean experimental codebase for the two preregistered EC-POMDG hypotheses.

## Quickstart — reproduce H1 and H2 on the SPHERE testbed engine

The canonical experiments run on the frozen five-stage `ec_pomdg` engine (the
same package deployed to the SPHERE defender). They reproduce the live
deploy-time validations and need no live Neo4j or attack traffic.

```bash
# 0. (first time) build the testbed + deploy the stack
bash pipeline/00_create_testbed.sh          # materialize the SPHERE topology
bash pipeline/deploy_all.sh                  # deploy plant, endpoints, telemetry, engine
bash pipeline/preflight_testbed.sh           # check services (optional for the experiments)

# 1. run the experiments (on the XDC host / defender, where ~/ecpomdg exists)
PYTHONPATH="$HOME/ecpomdg" python3 pipeline/run_experiments.py --seeds 200
#    -> writes results/{h1_policy_comparison,h2_inference_by_mode,h2_seen_twice}.csv + summary.md

# optional: (re)start the live-attack services (not needed for the experiments)
bash pipeline/activate_testbed.sh
```

Results and interpretation are in **`RESULTS.md`**. Headline: the
belief-conditioned defender is the only policy with 0 % real-compromise (H1);
DYNAMIC_KG > STATIC_KG > NO_KG stage-inference confidence (H2a); and DYNAMIC_KG
gains on attacks seen a second time while STATIC_KG is flat (H2b).

The sections below describe the hypotheses, the design invariants, and the
older offline-simulator path (`scripts/`), kept for unit tests and ablations.

## H1 — Multi-stage partially observable defense

Test whether a belief-conditioned adaptive defender improves cyber-physical resilience and/or reduces defensive cost compared with stage-agnostic and fixed policies in the same five-stage attacker-defender Markov game.

Hidden stages are fixed as:

1. RECON
2. ACCESS
3. DER_ENUM
4. CONTROL
5. IMPACT

Defender actions are fixed as:

- MONITOR
- ACTIVATE_DECOY
- REDIRECT
- CONTAIN

## H2 — Knowledge-graph-assisted Bayesian defense

Test whether temporally updated cyber-physical graph context improves hidden-stage inference and downstream defense compared with telemetry-only and frozen/static graph context.

Primary comparison:

- TELEMETRY_ONLY
- STATIC_KG
- DYNAMIC_KG

All comparisons must use matched attacker scenarios, seeds, observation censoring, defense budgets, and policy parameters.

## Design principles

- Never expose hidden stage, true target, attacker profile, random draws, or final outcome to the defender.
- Training/evaluation labels are evaluator-only and must be stored separately from defender-visible observations.
- H1 and H2 are tested separately first, then jointly.
- A fixed policy must not receive a hidden-stage shortcut.
- Containment is temporary/costly rather than an unconditional permanent episode terminator.
- Dynamic KG updates are derived only from observations available before the decision point.
- Final paper results come from matched SPHERE runs; the offline simulator is for unit tests, ablations, and pipeline validation only.

## Repository layout

- `src/ecpomdg_final/` — clean game, Bayesian inference, policies, KG interface, metrics.
- `configs/` — frozen experiment and stage-model configuration.
- `services/` — the small set of already validated SPHERE services retained from the earlier prototype.
- `topology/` — SPHERE testbed model.
- `scripts/` — preflight, Neo4j initialization, smoke tests, and final experiment runners.
- `tests/` — reproducibility and oracle-leakage tests.
- `docs/` — experimental protocol, current-code triage, and reference-code mapping.
- `results/` — generated output only; do not commit large run artifacts.

## Reproduce the offline results

```bash
cd ~/ecpomdg_final
pip install -r requirements.txt           # numpy, pandas, networkx (neo4j optional, for SPHERE)
python3 scripts/run_all_offline.py        # smoke + H2 + H1 + joint, writes results/*.json
python3 -m pytest -q tests                 # reproducibility + oracle-leakage tests
```

Individually:

```bash
python3 scripts/run_experiment_h2.py --episodes 400      # H2 stage inference
python3 scripts/run_experiment_h1.py --episodes 500      # H1 closed-loop policy comparison
python3 scripts/run_experiment_joint.py --episodes 400   # Experiment C: inference -> operational
```

The offline simulator (`src/ecpomdg_final/simulator.py`) exists to make the
observation process genuinely ambiguous — legitimate operator traffic, sensor
noise, and attack-free episodes — so the hypotheses are non-degenerate.
Paper-grade numbers come from matched SPHERE runs that reuse the same inference
(`dbn.py`), KG (`kg.py`), and policy (`policies.py`) code against live IEC-104
telemetry and a Neo4j graph. See `docs/EXPERIMENT_PROTOCOL.md` and
`RESULTS.md`.

### What the offline results show (seed-fixed, see `RESULTS.md`)

- **H2** — STATIC and DYNAMIC KG both significantly lower held-out stage
  log-loss versus telemetry-only; DYNAMIC vs STATIC is small and not
  significant (the static semantic/topological context carries most of it).
- **H1** — the belief-conditioned defender beats monitor-only and the reactive
  stage-agnostic policy, and edges a validation-tuned fixed schedule on overall
  utility by not spending defense during attack-free operations.
- **Joint (C)** — a DYNAMIC-KG belief defender significantly outperforms a
  telemetry-only belief defender on operational utility, so the inference gain
  translates into an operational gain.
- **Dynamic vs static (replay)** — when the same attacks recur, the DYNAMIC KG
  (cross-episode campaign memory in Neo4j) recognises the returning adversary at
  turn 0 and significantly beats the memoryless STATIC KG; the gap vanishes at
  zero recurrence. This is the SPHERE two-phase protocol in
  `RUNBOOK_SPHERE.md` §6 and `scripts/run_experiment_replay.py`.

## Run it on SPHERE

`RUNBOOK_SPHERE.md` has copy-paste commands from unzip through H1, H2, and the
dynamic-vs-static replay, mapped to the testbed nodes (Neo4j on `kg`, belief
filter on `defender`, IEC-104 attacker/collector/controller/decoy). The live
campaign replay uses `scripts/live/ecpomdg_live.py` (Neo4j store of record) and
`scripts/live/stage_collector_stream.py` (collector → stream glue).
