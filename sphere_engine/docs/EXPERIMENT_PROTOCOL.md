# Final experiment protocol

## Experiment A — H1 policy comparison

Freeze one observation/inference configuration before running H1. Use the same attack scenarios, seeds, observation censoring, and budget for every policy.

Primary policies:

1. FIXED_SCHEDULE — fixed actions by turn; no belief access.
2. STAGE_AGNOSTIC — reactive to current event severity only; no posterior.
3. BELIEF_ADAPTIVE — actions selected from posterior stage risk.

MONITOR_ONLY is retained as a negative control, not the main comparator.

Primary outcome: physical-impact rate. Secondary outcomes: real compromise, decoy diversion, defensive cost, utility, and time to intervention.

Containment is temporary and costly. It must not be implemented as a universal permanent episode terminator.

## Experiment B — H2 information comparison

Freeze one defender policy and one trained DBN structure. Evaluate identical held-out attack episodes under:

1. TELEMETRY_ONLY — raw trusted operational observations.
2. STATIC_KG — raw observations plus read-only semantic/topological graph features.
3. DYNAMIC_KG — same static graph plus pre-decision runtime observation nodes/edges and temporal path features.

The dynamic graph may contain only information available before the defender decision. Never insert evaluator labels, future physical effects, redirect success, attacker profile, or final outcome.

Primary outcome: held-out stage log loss. Secondary outcomes: multiclass Brier score, stage accuracy, target accuracy, detection lead time, and closed-loop decision utility.

## Experiment C — joint end-to-end confirmation

After A and B are frozen, run the BELIEF_ADAPTIVE policy under each knowledge mode to quantify whether any H2 inference gain translates into H1 operational gain.

## Split discipline

Split by complete episode/scenario family, never by individual event rows. Fit DBN parameters only on training episodes. Select thresholds on validation episodes. Report the untouched held-out test set once.

## Statistical reporting

Use paired seeds/scenarios. Report paired bootstrap confidence intervals for differences in rates/means and exact raw episode counts. Do not compare absolute reward values directly with unrelated papers or unrelated testbeds.

## Implementation notes (as realised in `src/`)

Three additions make the preregistered tests non-degenerate (the gap the
phase-3D.3 audit flagged). None of them redefine H1 or H2.

1. **Ambiguous observations** (`simulator.py`). Legitimate operator traffic
   emits the same IEC-104 event types an attacker does; sensors drop events and
   raise false alarms; the attacker can pivot through a trusted-looking host.
   So raw telemetry cannot cleanly separate the early stages, and the KG earns
   its keep by supplying the asset->physical mapping (`topology_risk`), source
   trust (`source_trust`), and the per-source escalation chain
   (`path_continuity`). These KG axes are deliberately non-redundant with
   `event_type` so the Bayesian emission product does not double-count one
   signal.

2. **A `NORMAL` (no-attack) belief state for H1** (`dbn.py` six-state model).
   The five-stage filter has no way to represent "no attacker", so its forward
   transition drifts belief upward on benign traffic and a belief policy can
   never stay quiet. The H1 filter adds a leading `NORMAL` state and is trained
   on a mix of attack and attack-free episodes. H2 keeps the five-stage
   inference-given-attack model.

3. **Operational cost and attack-free episodes** (`game.py`, `run_experiment_h1`).
   A maintained decoy and an active containment carry per-turn cost, and half of
   the H1 benchmark episodes contain no attacker. This is what lets a
   belief-conditioned policy pay off: spend defense only when an attack is
   believed present.

**Calibration.** Each DBN selects an emission temperature on the validation
split (`CategoricalStageDBN.calibrate`) to correct naive-Bayes overconfidence
from correlated features. Temperature is never selected on the test set.

**Reporting.** The attack base rate and operational-cost magnitudes
(`SimConfig`) change the H1 ranking and must be reported as sensitivity curves,
not single points.
