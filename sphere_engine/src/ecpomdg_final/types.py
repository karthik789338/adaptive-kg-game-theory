from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Mapping


class Stage(str, Enum):
    RECON = "RECON"
    ACCESS = "ACCESS"
    DER_ENUM = "DER_ENUM"
    CONTROL = "CONTROL"
    IMPACT = "IMPACT"


STAGE_ORDER = tuple(Stage)


class DefenderAction(str, Enum):
    MONITOR = "MONITOR"
    ACTIVATE_DECOY = "ACTIVATE_DECOY"
    REDIRECT = "REDIRECT"
    CONTAIN = "CONTAIN"


class KnowledgeMode(str, Enum):
    TELEMETRY_ONLY = "TELEMETRY_ONLY"
    STATIC_KG = "STATIC_KG"
    DYNAMIC_KG = "DYNAMIC_KG"


class PolicyMode(str, Enum):
    MONITOR_ONLY = "MONITOR_ONLY"
    FIXED_SCHEDULE = "FIXED_SCHEDULE"
    STAGE_AGNOSTIC = "STAGE_AGNOSTIC"
    BELIEF_ADAPTIVE = "BELIEF_ADAPTIVE"


class AttackerProfile(str, Enum):
    CAUTIOUS = "CAUTIOUS"
    PERSISTENT = "PERSISTENT"


@dataclass(frozen=True)
class Observation:
    event_type: str
    protocol_phase: str = "NONE"
    target_role: str = "UNKNOWN"
    physical_alarm: str = "NO"
    kg_source_trust: str = "UNKNOWN"
    kg_topology_risk: str = "UNKNOWN"
    kg_path_continuity: str = "UNKNOWN"
    kg_prior_campaign: str = "UNKNOWN_ACTOR"

    def features(self, mode: KnowledgeMode) -> dict[str, str]:
        # Raw IEC-104 wire telemetry only. Resolving which asset is physically
        # consequential (topology_risk) or whether a source is a trusted
        # operator (source_trust) requires the knowledge graph, so those live
        # behind the STATIC/DYNAMIC gate rather than in raw telemetry. These KG
        # axes are chosen to be non-redundant with event_type so the Bayesian
        # emission product does not double-count a single underlying signal.
        raw = {
            "event_type": self.event_type,
            "protocol_phase": self.protocol_phase,
            "physical_alarm": self.physical_alarm,
        }
        if mode in (KnowledgeMode.STATIC_KG, KnowledgeMode.DYNAMIC_KG):
            raw.update({
                "kg_source_trust": self.kg_source_trust,
                "kg_topology_risk": self.kg_topology_risk,
            })
        if mode is KnowledgeMode.DYNAMIC_KG:
            # Per-episode temporal chain AND cross-episode campaign memory.
            raw["kg_path_continuity"] = self.kg_path_continuity
            raw["kg_prior_campaign"] = self.kg_prior_campaign
        return raw


@dataclass(frozen=True)
class DefenderPublicState:
    decoy_active: bool
    containment_turns_remaining: int
    budget_remaining: int
    cumulative_defense_cost: float


@dataclass(frozen=True)
class DefenderView:
    belief: Mapping[str, float]
    observation: Observation
    public_state: DefenderPublicState
    previous_action: str | None
    turn: int


@dataclass(frozen=True)
class EpisodeRecord:
    episode_id: str
    seed: int
    turn: int
    knowledge_mode: str
    policy_mode: str
    observation: Mapping[str, Any]
    posterior: Mapping[str, float]
    defender_action: str
    public_state: Mapping[str, Any]
    evaluator: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
