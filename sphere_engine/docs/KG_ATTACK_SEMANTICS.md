# How attacks are represented in the knowledge graph

This is the semantics layer behind H2 and the Phase-3 live episode: how an
IEC-104 attack on the SPHERE testbed becomes queryable structure in Neo4j, and —
just as important — what that structure does *not* claim.

There are two layers on top of the three frozen KGs (general_cyber,
power_grid_ics, component_topology). Neither modifies the frozen core: both are
new node/edge types linked *to* existing frozen `:KGNode` anchors, and every
write is bracketed by a before/after fingerprint of the 6,742-node core
(`FROZEN_CORE_CRYPTOGRAPHICALLY_UNCHANGED: PASS`).

## Layer 1 — static calibrated bridges (Phase 3D.1C)

Five evidence-attested **`ECBridgeAssertion`** nodes connect a topology **asset**
to an ICS **behavior** it is calibrated to be capable of, via `BRIDGE_FROM`
(→ asset) and `BRIDGE_TO` (→ behavior) edges:

| bridge | asset (component_topology) | behavior (power_grid_ics) | relation |
|---|---|---|---|
| controller.general_interrogation | `ASSET::controller` | `BEHAVIOR::general-interrogation` | CALIBRATED_IEC104_INTERROGATION_CAPABILITY |
| controller.process_monitoring | `ASSET::controller` | `BEHAVIOR::process-state-monitoring` | CALIBRATED_IEC104_POINT_READ_CAPABILITY |
| controller.select_phase | `ASSET::controller` | `BEHAVIOR::select-execute-command` | CALIBRATED_IEC104_SELECT_PHASE_ONLY |
| decoy.control_transaction | `ASSET::decoy` | `BEHAVIOR::select-execute-command` | CALIBRATED_DECOY_IEC104_CONTROL_TRANSACTION |
| decoy.active_power_setpoint | `ASSET::decoy` | `BEHAVIOR::active-power-setpoint-manipulation` | CALIBRATED_DECOY_ACTIVE_POWER_SETPOINT |

Key scoping decisions, enforced in code:
- **Only Topology↔ICS bridges are approved.** `general_cyber` has **zero**
  event-specific bridges (`GENERAL_CYBER_BRIDGES_APPROVED: 0`). This is why the
  8-mask ablation shows general-cyber adding nothing: it is background context,
  not an attack-anchored graph.
- The bridges assert **calibrated capability**, derived from four frozen 3C.8C
  calibration episodes (recorded in `phase3d1c_calibration_evidence_attestation.json`),
  **not** attack intent, hidden stage, or outcome.
- A manifest↔attestation SHA-256 chain binds each bridge to its evidence; the
  manager refuses to write if either drifts.

## Layer 2 — per-episode observations (Phase 3D.1D / live 3D.2A)

Each live episode's **trusted, pre-decision** IEC-104 observations become an
**`ECEpisode`** node plus one **`ECObservation`** per event, wired to the frozen
anchors:
- `HAS_OBSERVATION`: episode → each observation
- `OBSERVED_ON`: observation → the topology asset (`ASSET::controller`, trusted
  `asset-field-001`)
- `CLASSIFIED_AS`: observation → the ICS behavior, by this fixed map:

  | IEC-104 event | ICS behavior |
  |---|---|
  | `iec104_interrogation` | `general-interrogation` |
  | `iec104_point_read` | `process-state-monitoring` |
  | `iec104_select` | `select-execute-command` |

  (`iec104_connection_request` / `iec104_session_established` are recorded as
  session evidence; they carry no behavior edge.)

The point reads must cover the three DER IOAs `{11, 12, 13}` and there must be
exactly one real `select` (IOA 100, SELECT-only, never EXECUTE) — the same
evidence prefix the live coordinator validates on the wire.

So "adding an attack to the KG" = recording **which asset was observed doing
which ICS behavior, in which episode, before the defender decided** — and,
through the Layer-1 bridges, whether that behavior is a *calibrated capability*
of that asset. In the live run this is what makes the Topology+ICS (`I_T`) mask
light up: `IT_BRIDGED=8` observations are both ICS-classified *and*
topology-bridged, versus 0 under general-cyber-only masks.

## What this is NOT (read before citing KG efficacy)

- It is **not** a learned or validated Bayesian likelihood feature. In every
  run the readback reports `GRAPH_FEATURES_IN_BAYESIAN_LIKELIHOOD: NO` and
  `DYNAMIC_KG_BELIEF_ADVANTAGE_ESTABLISHED: NO`. The online graph commit+read is
  a **mandatory evidence/continuation gate** proving commit→read ordering before
  the decision, not a claim that the KG improved the decision.
- The episodes used to calibrate the bridges and to validate the live
  integration are **excluded** from any held-out efficacy evaluation
  (`EXCLUDED` set in `manage_phase3d1d`, and the 3C.8C calibration set).
- Attacker stage, defender action, terminal outcome, and post-decision decoy
  actions are **omitted** from the snapshot the graph ever sees.

Where the KG's measured effect actually lives: the stage-inference confidence
gain (H2a), the seen-twice dynamic gain (H2b), and the 8-mask ablation isolating
the **ICS** KG as the contributor — all in `RESULTS.md`.
