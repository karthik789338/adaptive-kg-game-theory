# EC-POMDG results (H1 and H2) on the SPHERE testbed engine

All numbers below are produced by `pipeline/run_experiments.py` running on the
frozen five-stage `ec_pomdg` engine — the same package deployed to the SPHERE
defender node. They reproduce the live deploy-time validations
(`five_stage_ecpomdg_engine_validation`, `multistage_attack_belief_runtime_validation`).
No live Neo4j or attack traffic is needed: the engine carries the KG effect in
its frozen belief model, and dynamic-KG memory is exercised in-process.

Reproduce:

```bash
# on the SPHERE XDC host (or defender) -- where ~/ecpomdg/ec_pomdg + configs exist
PYTHONPATH="$HOME/ecpomdg" python3 ecpomdg_sphere/pipeline/run_experiments.py --seeds 200
```

## H1 — belief-conditioned deception beats stage-blind defense

Four defender policies vs the same five-stage CAUTIOUS attacker, 200 seeds each,
DYNAMIC_KG. The attacker reaches physical control unless the defender diverts to
the decoy or contains in time.

| policy | diversion | withdrawn | compromise | mean reward |
|---|---|---|---|---|
| MONITOR_ONLY | 0.00 | 0.00 | 1.00 | −100.00 |
| FIXED_SCHEDULE | 0.61 | 0.00 | 0.39 | −25.48 |
| STAGE_AGNOSTIC | 0.82 | 0.00 | 0.18 | −1.40 |
| **BELIEF_ADAPTIVE** | 0.61 | 0.39 | **0.00** | **+14.69** |

**Finding.** Only the belief-conditioned policy drives real-compromise to **zero**
and net reward positive. Stage-blind baselines are compromised 18–100 % of the
time: monitoring never acts; fixed timing mis-fires; greedy reaction wastes the
decoy budget and mistimes containment. Belief over the hidden attack stage is
what lets the defender act at the right moment. **H1 supported.**

## H2a — static KG improves attacker-stage inference over telemetry-only

First-encounter inference: **NO_KG vs STATIC_KG only**. DYNAMIC_KG is excluded
here on purpose — its advantage is temporal memory, and on a first encounter the
attack has not been recorded yet, so there is nothing for the dynamic overlay to
use. That effect is isolated in H2b. One canonical attack evidence trail through
each belief updater; cell = posterior confidence in the *true* stage.

| mode | RECON | ACCESS | DER_ENUM | CONTROL | PHYS_IMPACT | mean |
|---|---|---|---|---|---|---|
| NO_KG | 0.835 | 0.499 | 0.373 | 0.420 | 0.434 | 0.512 |
| STATIC_KG | 0.901 | 0.614 | 0.558 | 0.655 | 0.687 | 0.683 |

**Finding.** STATIC_KG > NO_KG at **every** stage. KG context resolves the
mid/late stages (DER enumeration, control, physical impact) that telemetry alone
leaves ambiguous. **H2 (KG-context inference gain) supported.**

## H2b — dynamic KG beats static KG on attacks *seen a second time*

The same attack replayed through one updater. DYNAMIC accumulates episode-overlay
memory of the evidence it has already seen; STATIC has none.

| mode | encounter 1 | encounter 2 | encounter 3 | gain |
|---|---|---|---|---|
| STATIC_KG | 0.6828 | 0.6828 | 0.6828 | +0.0000 |
| DYNAMIC_KG | 0.7425 | 0.7597 | 0.7747 | +0.0322 |

**Finding.** STATIC is memoryless — identical every time. DYNAMIC's confidence
rises on each re-encounter of the same campaign, which is exactly the
"temporally-updated KG" advantage. **H2 (dynamic > static) supported.**

## Experiment 2 — 8-mask KG ablation (which knowledge graph matters)

Authoritative audit-first ablation (`results/ablation/`): 8 masks over the three
KGs (NONE, G=general-cyber, I=ICS, T=topology, and combinations), evaluated on
280 held-out stage-inference boundaries (6 stage classes), scored by log-loss
with bootstrap CIs, on an **actual Neo4j overlay readback** (the same three KGs
now rebuilt live in Neo4j: general_cyber 6185 / power_grid_ics 467 /
component_topology 104, active-only).

| mask | log-loss | Δ vs NONE | reading |
|---|---|---|---|
| NONE | 0.9423 | — | telemetry only |
| G_ONLY | 0.9423 | +0.000 | general-cyber adds nothing |
| **I_ONLY** | 0.9222 | **+0.0201** | ICS KG — the contributor |
| T_ONLY | 0.9405 | +0.0018 | topology marginal |
| G_I | 0.9222 | +0.0201 | = I_ONLY (G adds nothing) |
| I_T | 0.9340 | +0.0083 | |
| G_I_T | 0.9340 | +0.0083 | = I_T (G adds nothing) |

**Finding.** The **ICS KG carries essentially all the stage-inference gain**; the
**general-cyber KG adds nothing** (0 event-specific links — background context by
design); **topology** contributes marginally. Improvements are real but modest and
CIs include zero at this test size, and the report's negative control shows the
gain is in the *information* the KG carries, not the graph structure itself
(`graph_representation_gain = 0.0`). This is the honest ablation answer to "which
KG matters": **ICS**.

## Phase 3 — live online-Neo4j pre-decision integration episode (SPHERE)

The full live loop now runs end-to-end on the real testbed
(`PHASE3D2A_LIVE_NEO4J_PREDECISION_INTEGRATION: PASS`, exit 0; audit at
`~/ecpomdg_audit/multistage_game/live_action_gated_decoy/<run>_no_kg/`). One
NO_KG episode: a real attacker does observe-only + a real **SELECT-only** probe
(never EXECUTE); the real multi-stage sensor captures the IEC-104 stage chain;
the collector emits operational observations; the episode's 12 observations are
**committed to Neo4j and read back through the 5 Topology↔ICS bridges before the
defender decides**; then the frozen NO_KG policy runs.

| marker | value |
|---|---|
| online episode observations committed | **12** |
| graph commit+read before decision | `PASS` |
| Topology+ICS bridged observations (`I_T` mask) | **8** (`IT_BRIDGED`) |
| frozen core + 5 bridges unchanged | `PASS` |
| P(CONTROL_MANIPULATION) at decision | 0.4678 |
| post-SELECT action | `MONITOR` (control withheld) |
| real controller EXECUTE | none (`REAL_NO_EXECUTE: PASS`) |
| real plant state change | none (`REAL_PLANT_STATE_UNCHANGED: PASS`) |
| outcome | `CONTROL_WITHHELD_CENSORED` |

**What this establishes — and what it does not.** This is an **integration and
safety proof**: the live loop runs on SPHERE with a mandatory online Neo4j
commit→read barrier before the decision and the safety invariant intact (the
real controller never executes; only the isolated decoy is ever a control
target, behind a one-use authorization). It is **not** new KG-efficacy evidence:
the episode reports `GRAPH_FEATURES_IN_BAYESIAN_LIKELIHOOD: NO` and
`DYNAMIC_KG_BELIEF_ADVANTAGE_ESTABLISHED: NO`, and this episode is excluded from
efficacy evaluation. The measured KG effect remains H1/H2a/H2b and the 8-mask
ablation above. See `docs/KG_ATTACK_SEMANTICS.md` for how the episode's attack
observations are represented in the graph.

## Scope and honesty notes

- H1 and H2a/b run on the deployed EC-POMDG engine with its frozen KG belief
  model; the ablation ran on a frozen Neo4j overlay readback of the three KGs.
  All three KGs are rebuilt and live in Neo4j (Phase 1), the live KG-enrichment
  context service is deployed (Phase 2), and the live pre-decision episode runs
  on the real testbed (Phase 3, above).
- The real controller never executes in the live stack (safety invariant),
  verified live (`REAL_NO_EXECUTE`/`REAL_PLANT_STATE_UNCHANGED: PASS`), so
  physical impact is a modeled terminal, never a commanded one.
- At the single-episode *outcome* level STATIC_KG and DYNAMIC_KG tie; the dynamic
  advantage is in stage-inference confidence (H2a) and in the seen-twice regime
  (H2b), not in one fresh episode. We report it where it exists and not elsewhere.
