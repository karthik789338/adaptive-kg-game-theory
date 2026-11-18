"""Stochastic emission simulator with benign confounders.

The old prototype emitted exactly one event type per hidden stage with no
noise, which made ``event_type`` bijective with the stage: telemetry-only
inference was already perfect and no knowledge-graph context could add or lose
anything. That degeneracy is why the earlier eight-KG ablation found zero
separation.

This module makes the observation process genuinely ambiguous, the way real
ICS telemetry is:

* Legitimate operator traffic emits the same IEC-104 event types an attacker
  does (general interrogation, point reads, even occasional setpoint commands).
* Sensors drop events and raise occasional false alarms.
* The attacker can occasionally pivot through a trusted-looking host
  (living-off-the-land), so source trust is an imperfect separator.

Under this model telemetry alone cannot cleanly separate ACCESS / DER_ENUM /
benign activity; the knowledge graph earns its keep by supplying the
asset->physical-consequence mapping and the per-source escalation chain that
raw telemetry does not carry. The emission process is identical across
knowledge modes, so H2 re-featurises the *same* raw events under each mode and
every comparison is exactly matched.
"""
from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Optional

from .offline_kg import OfflineKG, EpisodeRuntimeGraph
from .types import AttackerProfile, KnowledgeMode, Observation, Stage, STAGE_ORDER


# --- emission probability tables ------------------------------------------
# P(event_type | attacker is actively acting at this hidden stage)
# A stealthy attacker: the early stages (RECON/ACCESS/DER_ENUM) share the same
# low-signal wire events (interrogation / reads / silence), so no single event
# type pins which of them the attacker is in. Only CONTROL/IMPACT emit
# protocol-unique select/execute. This is where semantic (which asset) and
# temporal (how deep the escalation chain) graph context must carry the stage
# signal the raw protocol stream cannot.
_ATTACKER_EMISSION: dict[str, dict[str, float]] = {
    "RECON":    {"NETWORK_RECON": 0.30, "GENERAL_INTERROGATION": 0.30, "NO_ACTIVITY": 0.40},
    "ACCESS":   {"IEC104_SESSION": 0.25, "GENERAL_INTERROGATION": 0.40, "NO_ACTIVITY": 0.35},
    "DER_ENUM": {"GENERAL_INTERROGATION": 0.45, "POINT_READ": 0.40, "NO_ACTIVITY": 0.15},
    "CONTROL":  {"CONTROL_SELECT": 0.70, "GENERAL_INTERROGATION": 0.20, "NO_ACTIVITY": 0.10},
    "IMPACT":   {"CONTROL_EXECUTE": 0.80, "CONTROL_SELECT": 0.10, "NO_ACTIVITY": 0.10},
}

# P(event_type | legitimate operator traffic this turn)
_BENIGN_EMISSION: dict[str, float] = {
    "GENERAL_INTERROGATION": 0.40,
    "POINT_READ": 0.35,
    "NO_ACTIVITY": 0.15,
    "CONTROL_SELECT": 0.07,
    "CONTROL_EXECUTE": 0.03,
}

_UNTRUSTED_SOURCES = ("attacker", "edgegw")


@dataclass(frozen=True)
class SimConfig:
    """All knobs that shape observation ambiguity (reported for sensitivity)."""
    benign_rate: float = 0.45          # fraction of turns showing operator traffic
    lotl_rate: float = 0.15            # attacker pivots through a trusted-looking host
    operator_mislabel_rate: float = 0.08  # benign traffic that looks untrusted
    sensor_drop_rate: float = 0.08     # event dropped -> NO_ACTIVITY seen
    false_alarm_rate: float = 0.04     # spurious physical alarm
    impact_alarm_rate: float = 0.60    # true physical alarm when real IMPACT fires
    cautious_advance: float = 0.55
    persistent_advance: float = 0.80
    max_turns: int = 12
    # Operational cost of running deception/containment against live operations.
    decoy_hold_cost: float = 0.6      # per-turn cost while a decoy is maintained
    containment_op_penalty: float = 4.0  # per-turn disruption to legitimate control


def _weighted_choice(rng: random.Random, table: dict[str, float]) -> str:
    r = rng.random()
    cumulative = 0.0
    for key, weight in table.items():
        cumulative += weight
        if r <= cumulative:
            return key
    return next(reversed(table))


def _asset_and_role(event_type: str, stage: str, is_benign: bool, rng: random.Random, target: str = "REAL"):
    """Return (asset_id, target_role) for a raw event (defender-visible)."""
    if event_type == "NO_ACTIVITY":
        return "UNKNOWN", "UNKNOWN"
    if is_benign:
        if event_type in ("CONTROL_SELECT", "CONTROL_EXECUTE"):
            return "controller-real", "REAL"      # legitimate setpoint change
        return rng.choice(["historian", "scada-hmi"]), rng.choice(["HISTORIAN", "SCADA"])
    # attacker
    if stage in ("RECON", "ACCESS"):
        return rng.choice(["scada-hmi", "historian"]), "SCADA"
    # Once redirected onto the decoy, control/impact activity hits the decoy
    # controller, which the topology KG knows is not grid-coupled.
    if target == "DECOY" and stage in ("CONTROL", "IMPACT"):
        return "controller-decoy", "DECOY"
    role = "REAL"
    if rng.random() < 0.05:
        role = "UNKNOWN"  # coarse/missing role labelling in telemetry
    return "controller-real", role


def _source_host(is_benign: bool, rng: random.Random, config: SimConfig) -> str:
    if is_benign:
        if rng.random() < config.operator_mislabel_rate:
            return rng.choice(_UNTRUSTED_SOURCES)
        return rng.choice(["scada-hmi", "operator", "historian"])
    # attacker
    if rng.random() < config.lotl_rate:
        return "scada-hmi"  # living-off-the-land: trusted-looking origin
    return rng.choice(list(_UNTRUSTED_SOURCES))


def sample_raw_event(
    stage: str,
    is_benign: bool,
    rng: random.Random,
    config: SimConfig,
    real_impact_fired: bool = False,
    target: str = "REAL",
) -> dict:
    """Sample one defender-visible raw event (no hidden fields)."""
    if is_benign:
        event_type = _weighted_choice(rng, _BENIGN_EMISSION)
    else:
        event_type = _weighted_choice(rng, _ATTACKER_EMISSION[stage])

    # Sensor drop.
    if rng.random() < config.sensor_drop_rate:
        event_type = "NO_ACTIVITY"

    asset_id, target_role = _asset_and_role(event_type, stage, is_benign, rng, target)
    source_host = _source_host(is_benign, rng, config) if event_type != "NO_ACTIVITY" else "UNKNOWN"

    phase = "SELECT" if event_type == "CONTROL_SELECT" else ("EXECUTE" if event_type == "CONTROL_EXECUTE" else "NONE")

    alarm = False
    if real_impact_fired and not is_benign and rng.random() < config.impact_alarm_rate:
        alarm = True
    elif rng.random() < config.false_alarm_rate:
        alarm = True

    return {
        "event_type": event_type,
        "protocol_phase": phase,
        "target_role": target_role,
        "asset_id": asset_id,
        "source_host": source_host,
        "physical_alarm": "YES" if alarm else "NO",
    }


def featurize(raw_event: dict, kg: OfflineKG, runtime: EpisodeRuntimeGraph, mode: KnowledgeMode,
              memory=None, asof: float = 0.0) -> Observation:
    """Turn a raw event into a mode-specific defender Observation via the KG.

    ``memory``/``asof`` (DYNAMIC only) attach the cross-episode campaign prior.
    """
    ctx = kg.context_for(raw_event, runtime, KnowledgeMode(mode).value, memory=memory, asof=asof)
    return Observation(
        event_type=raw_event["event_type"],
        protocol_phase=raw_event["protocol_phase"],
        target_role=raw_event["target_role"],
        physical_alarm=raw_event["physical_alarm"],
        kg_source_trust=ctx.source_trust,
        kg_topology_risk=ctx.topology_risk,
        kg_path_continuity=ctx.path_continuity,
        kg_prior_campaign=ctx.prior_campaign,
    )


def generate_inference_episode(seed: int, profile: AttackerProfile, config: Optional[SimConfig] = None,
                               has_attacker: bool = True, actor_id: Optional[str] = None) -> list[dict]:
    """Generate one passive inference episode: a list of turns.

    Each turn dict carries the hidden ``true_stage`` (evaluator-only) and the
    defender-visible ``raw_event``. Knowledge-mode featurisation is applied
    later so the same raw stream is scored identically across modes.

    ``actor_id`` attributes the whole episode to one observed adversary/operator
    identity (a campaign), which the cross-episode dynamic KG remembers.
    """
    config = config or SimConfig()
    profile = AttackerProfile(profile)
    rng = random.Random((seed * 2654435761) & 0xFFFFFFFF)  # emission/benign stream
    advance_rng = random.Random((seed * 40503 + 7) & 0xFFFFFFFF)  # progression stream

    advance = config.cautious_advance if profile is AttackerProfile.CAUTIOUS else config.persistent_advance
    stage_idx = 0
    turns: list[dict] = []
    real_impact_fired = False

    actor = actor_id if actor_id is not None else (f"actor-{seed}" if has_attacker else f"operator-{seed}")

    for _ in range(config.max_turns):
        if not has_attacker:
            # Attack-free episode: only legitimate operations; label NORMAL.
            raw = sample_raw_event("RECON", True, rng, config)
            raw["actor_id"] = actor
            turns.append({"true_stage": "NORMAL", "raw_event": raw, "is_benign_evaluator_only": True})
            continue
        stage = STAGE_ORDER[stage_idx].value
        is_benign = rng.random() < config.benign_rate
        if stage == "IMPACT" and not is_benign:
            real_impact_fired = True
        raw = sample_raw_event(stage, is_benign, rng, config, real_impact_fired=real_impact_fired)
        raw["actor_id"] = actor
        turns.append({"true_stage": stage, "raw_event": raw, "is_benign_evaluator_only": is_benign})

        # Passive hidden progression (defender does not act in inference episodes).
        if stage_idx < len(STAGE_ORDER) - 1 and advance_rng.random() < advance:
            stage_idx += 1

    return turns
