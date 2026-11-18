from __future__ import annotations
from typing import Mapping

from ..kg import KGContext
from ..types import Observation
from .oracle_guard import assert_defender_visible


def observation_from_operational_event(event: Mapping, context: KGContext) -> Observation:
    payload = dict(event)
    assert_defender_visible(payload)
    event_type = str(payload.get("event_type", "UNKNOWN"))
    phase = str(payload.get("command_phase", "NONE") or "NONE").upper()
    target_role = str(payload.get("asset_role", payload.get("role", "UNKNOWN"))).upper()
    physical_alarm = "YES" if bool(payload.get("physical_alarm", False)) else "NO"
    return Observation(
        event_type=event_type,
        protocol_phase=phase,
        target_role=target_role,
        physical_alarm=physical_alarm,
        kg_source_trust=context.source_trust,
        kg_topology_risk=context.topology_risk,
        kg_path_continuity=context.path_continuity,
    )
