"""Offline, non-oracle knowledge-graph feature provider.

This mirrors the Neo4j schema in ``docs/NEO4J_DESIGN.md`` but runs on an
in-memory NetworkX graph so offline ablations and unit tests do not require a
database. The three knowledge domains from the paper are kept logically
distinct:

* ``component_topology``  -> which asset drives a physical process (REAL vs
  DECOY vs read-only/historian). This is the knowledge raw telemetry does not
  carry: the collector sees ``asset-field-010`` but not that field-010 is a
  grid-coupled inverter setpoint.
* ``power_grid_ics``      -> IEC-104 behaviour / technique semantics and which
  source hosts are trusted operators versus untrusted.
* ``general_cyber``       -> ATT&CK-for-ICS technique ordering used as the
  stage-progression prior (consumed by the DBN transition fit, not leaked here).

CRITICAL: every value returned here is computed only from defender-visible
fields of the observed event and from observations already seen earlier in the
same episode. No hidden stage, true target, attacker profile, redirect draw,
or future effect is ever read. The KG supplies *mappings*, not labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import networkx as nx

from .kg import KGContext


# --- static ontology -------------------------------------------------------

# Assets that are physically consequential if commanded.
_PHYSICAL_CONTROL_ASSETS = {"controller-real", "ctrl-field-001"}
_READ_ONLY_ASSETS = {"historian", "scada-hmi"}
_DECOY_ASSETS = {"controller-decoy", "ctrl-field-099"}

# Source hosts the ICS KG recognises as authorised operator origins.
_TRUSTED_SOURCES = {"scada-hmi", "operator", "historian"}

# event_type -> coarse ICS technique phase (many-to-one; NOT the hidden stage).
_EVENT_TECHNIQUE = {
    "NETWORK_RECON": "DISCOVERY",
    "IEC104_SESSION": "INITIAL_ACCESS",
    "GENERAL_INTERROGATION": "COLLECTION",
    "POINT_READ": "COLLECTION",
    "CONTROL_SELECT": "COMMAND_STAGING",
    "CONTROL_EXECUTE": "IMPACT",
    "NO_ACTIVITY": "NONE",
}


def build_static_graph() -> nx.MultiDiGraph:
    """Construct the frozen semantic/topology graph used for STATIC_KG."""
    g = nx.MultiDiGraph()
    g.add_node("grid", kind="physical_process", domain="component_topology")
    for asset in _PHYSICAL_CONTROL_ASSETS:
        g.add_node(asset, kind="controller", domain="component_topology")
        g.add_edge(asset, "grid", rel="CONTROLS_PHYSICAL_PROCESS")
    for asset in _READ_ONLY_ASSETS:
        g.add_node(asset, kind="read_only", domain="component_topology")
    for asset in _DECOY_ASSETS:
        # Deliberately NOT connected to the grid: decoy cannot cause impact.
        g.add_node(asset, kind="decoy", domain="component_topology")
    for event, technique in _EVENT_TECHNIQUE.items():
        g.add_node(f"evt::{event}", domain="power_grid_ics")
        g.add_node(f"tech::{technique}", domain="general_cyber")
        g.add_edge(f"evt::{event}", f"tech::{technique}", rel="EXHIBITS_TECHNIQUE")
    return g


@dataclass
class EpisodeRuntimeGraph:
    """Per-episode runtime overlay for DYNAMIC_KG (temporal path features).

    Holds the escalation chain of techniques seen per source host so far in the
    episode. Only observations already processed are present, so a decision at
    turn t sees nothing from turn > t.
    """

    source_chain: dict[str, list[str]] = field(default_factory=dict)

    def record(self, source_host: str, technique: str) -> None:
        if technique in ("NONE",):
            return
        self.source_chain.setdefault(source_host, []).append(technique)

    def continuity_for(self, source_host: str) -> str:
        chain = self.source_chain.get(source_host, [])
        distinct = list(dict.fromkeys(chain))  # order-preserving unique
        escalation_rank = {
            "DISCOVERY": 0,
            "INITIAL_ACCESS": 1,
            "COLLECTION": 2,
            "COMMAND_STAGING": 3,
            "IMPACT": 4,
        }
        ranks = [escalation_rank.get(t, -1) for t in distinct if t in escalation_rank]
        if len(ranks) >= 3 and ranks == sorted(ranks):
            return "CONSISTENT_ESCALATION"
        if len(ranks) >= 2 and ranks == sorted(ranks):
            return "EMERGING_CHAIN"
        if len(chain) >= 2:
            return "STEADY"  # repeated same-technique traffic (benign polling)
        return "SPARSE"


class OfflineKG:
    """Static + dynamic KG feature provider for offline H2 ablations.

    Parameters
    ----------
    trust_noise:
        Probability-independent hook left at 0.0 here; the *simulator* injects
        living-off-the-land / mislabelled-operator noise into ``source_host`` so
        source trust is an imperfect separator. The KG itself is deterministic.
    """

    def __init__(self) -> None:
        self.graph = build_static_graph()

    # -- static -------------------------------------------------------------
    def _topology_risk(self, asset_id: str) -> str:
        if asset_id in _PHYSICAL_CONTROL_ASSETS:
            return "HIGH"
        if asset_id in _DECOY_ASSETS:
            return "DECOY"
        if asset_id in _READ_ONLY_ASSETS:
            return "LOW"
        return "UNKNOWN"

    def _source_trust(self, source_host: str) -> str:
        if source_host == "UNKNOWN":
            return "UNKNOWN"
        return "TRUSTED" if source_host in _TRUSTED_SOURCES else "UNTRUSTED"

    # -- public -------------------------------------------------------------
    def context_for(
        self,
        raw_event: Mapping[str, str],
        runtime: EpisodeRuntimeGraph,
        mode: str,
        memory=None,
        asof: float = 0.0,
    ) -> KGContext:
        """Return a KGContext for ``mode`` in {TELEMETRY_ONLY, STATIC_KG, DYNAMIC_KG}.

        ``runtime`` must already contain every earlier observation in the
        episode; this method records the current event into it *after* reading
        continuity, so the feature reflects only the pre-decision chain.

        ``memory`` (a CampaignMemory, DYNAMIC only) supplies the cross-episode
        prior-campaign category for the event's observed actor identity, read
        with the pre-decision ``asof`` cutoff. STATIC never consults it.
        """
        if mode == "TELEMETRY_ONLY":
            return KGContext()

        event_type = str(raw_event.get("event_type", "UNKNOWN"))
        asset_id = str(raw_event.get("asset_id", "UNKNOWN"))
        source_host = str(raw_event.get("source_host", "UNKNOWN"))

        trust = self._source_trust(source_host)
        risk = self._topology_risk(asset_id)
        continuity = "UNKNOWN"
        prior_campaign = "UNKNOWN_ACTOR"

        if mode == "DYNAMIC_KG":
            continuity = runtime.continuity_for(source_host)
            if memory is not None:
                actor_id = str(raw_event.get("actor_id", source_host))
                prior_campaign = memory.prior_campaign(actor_id, asof)

        # Record AFTER computing continuity so the pre-decision chain is used.
        runtime.record(source_host, _EVENT_TECHNIQUE.get(event_type, "NONE"))
        return KGContext(source_trust=trust, topology_risk=risk,
                         path_continuity=continuity, prior_campaign=prior_campaign)
