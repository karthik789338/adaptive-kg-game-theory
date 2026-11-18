from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .types import KnowledgeMode


@dataclass(frozen=True)
class KGContext:
    source_trust: str = "UNKNOWN"
    topology_risk: str = "UNKNOWN"
    path_continuity: str = "UNKNOWN"
    prior_campaign: str = "UNKNOWN_ACTOR"  # cross-episode campaign memory (DYNAMIC only)


class Neo4jKG:
    """Neo4j source-of-truth for static and runtime cyber-physical graph context.

    NetworkX may be used in tests/visualization, but final H2 feature extraction
    should come from the same Neo4j schema used in the live SPHERE experiment.
    """

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        from neo4j import GraphDatabase
        self._driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=15)
        self.database = database

    def close(self) -> None:
        self._driver.close()

    def record_observation(self, episode_id: str, event: Mapping[str, Any]) -> None:
        query = """
        MERGE (e:Episode {episode_id:$episode_id})
        CREATE (o:RuntimeObservation {
            event_id:$event_id,
            ts_utc:$ts_utc,
            event_type:$event_type,
            asset_id:$asset_id,
            protocol_phase:$protocol_phase,
            ioa:$ioa
        })
        MERGE (e)-[:HAS_OBSERVATION]->(o)
        WITH e,o
        OPTIONAL MATCH (prev:RuntimeObservation)<-[:HAS_OBSERVATION]-(e)
        WHERE prev.event_id <> o.event_id AND prev.ts_utc <= o.ts_utc
        WITH o, prev ORDER BY prev.ts_utc DESC LIMIT 1
        FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END |
            MERGE (prev)-[:NEXT_OBSERVATION]->(o)
        )
        """
        params = {
            "episode_id": episode_id,
            "event_id": str(event.get("event_id", "")),
            "ts_utc": str(event.get("collector_ts_utc") or datetime.now(timezone.utc).isoformat()),
            "event_type": str(event.get("event_type", "UNKNOWN")),
            "asset_id": str(event.get("asset_id", "UNKNOWN")),
            "protocol_phase": str(event.get("command_phase", "NONE")),
            "ioa": event.get("ioa"),
        }
        with self._driver.session(database=self.database) as session:
            session.run(query, **params).consume()

    def context_for_observation(self, episode_id: str, event: Mapping[str, Any], mode: KnowledgeMode) -> KGContext:
        mode = KnowledgeMode(mode)
        if mode is KnowledgeMode.TELEMETRY_ONLY:
            return KGContext()

        asset_id = str(event.get("asset_id", "UNKNOWN"))
        source_host = str(event.get("source_host", "UNKNOWN"))
        static_query = """
        OPTIONAL MATCH (a {asset_id:$asset_id})-[:CONTROLS_PHYSICAL_PROCESS|CONTROLS_PHYSICAL_GRID*1..3]->(p)
        OPTIONAL MATCH (src:Source {host:$source_host})
        RETURN CASE WHEN count(p)>0 THEN 'HIGH' ELSE 'LOW' END AS topology_risk,
               coalesce(src.trust,'UNKNOWN') AS source_trust
        LIMIT 1
        """
        with self._driver.session(database=self.database) as session:
            row = session.run(static_query, asset_id=asset_id, source_host=source_host).single()
            risk = row["topology_risk"] if row else "UNKNOWN"
            trust = row["source_trust"] if row else "UNKNOWN"

            continuity = "UNKNOWN"
            if mode is KnowledgeMode.DYNAMIC_KG:
                dynamic_query = """
                MATCH (:Episode {episode_id:$episode_id})-[:HAS_OBSERVATION]->(o:RuntimeObservation)
                WHERE o.source_host = $source_host
                WITH count(DISTINCT o.event_type) AS depth
                RETURN CASE WHEN depth >= 3 THEN 'CONSISTENT_ESCALATION'
                            WHEN depth = 2 THEN 'EMERGING_CHAIN'
                            WHEN depth = 1 THEN 'STEADY' ELSE 'SPARSE' END AS continuity
                """
                drow = session.run(dynamic_query, episode_id=episode_id, source_host=source_host).single()
                continuity = drow["continuity"] if drow else "SPARSE"
        return KGContext(source_trust=trust, topology_risk=risk, path_continuity=continuity)
