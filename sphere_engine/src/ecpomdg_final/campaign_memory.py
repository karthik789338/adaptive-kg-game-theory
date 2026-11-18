"""Cross-episode campaign memory — the dynamic KG's decisive advantage.

A static knowledge graph holds only the frozen ontology/topology: it has no
memory of attacks that already happened. A *dynamic* KG accumulates confirmed
threat intelligence over time, so when the same adversary returns it is
recognised immediately and the belief filter sharpens before the telemetry on
its own could resolve the stage.

This is the mechanism behind the SPHERE two-phase protocol:

    Phase 1 (learn)  : run attack campaigns; after each episode is adjudicated,
                       record the observed actor identity and its confirmed
                       outcome into the campaign store (Neo4j on SPHERE).
    Phase 2 (replay) : run the SAME campaigns again. STATIC_KG has no memory and
                       must re-infer from scratch; DYNAMIC_KG retrieves the prior
                       campaign for that actor and gains a head start.

Non-oracle guarantees:
* Memory is written only from PAST, fully-completed episodes, and read with an
  as-of cutoff strictly before the current decision time.
* Benign operator identities recur and are recorded as benign too, so a "known"
  actor is not synonymous with an attacker — only confirmed-attacker actors
  help. Novel (never-seen) actors give no benefit, so the measured advantage is
  exactly proportional to campaign recurrence, which is the honest claim.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

# Defender-visible categorical the dynamic filter consumes. It encodes what the
# accumulated threat intel says about this actor BEFORE the current episode.
PRIOR_UNKNOWN = "UNKNOWN_ACTOR"       # never observed before
PRIOR_BENIGN = "KNOWN_BENIGN_ACTOR"   # seen before, confirmed benign operator
PRIOR_ATTACK_EARLY = "KNOWN_ATTACKER_EARLY"  # prior campaign stopped early
PRIOR_ATTACK_LATE = "KNOWN_ATTACKER_LATE"    # prior campaign reached control/impact

_LATE_STAGES = {"CONTROL", "IMPACT"}


@dataclass
class _ActorRecord:
    observations: list = field(default_factory=list)  # (asof, is_attack, max_stage_rank)


class CampaignMemory:
    """In-memory campaign store (mirror of the SPHERE Neo4j schema).

    Keyed by the observed actor identity (a stable source fingerprint the
    collector reports — host cert, client id, or source address). Records carry
    an as-of clock so reads can enforce the pre-decision cutoff.
    """

    _STAGE_RANK = {"NORMAL": 0, "RECON": 1, "ACCESS": 2, "DER_ENUM": 3, "CONTROL": 4, "IMPACT": 5}

    def __init__(self) -> None:
        self._actors: dict[str, _ActorRecord] = defaultdict(_ActorRecord)

    def record_campaign(self, actor_id: str, is_attack: bool, max_stage: str, asof: float) -> None:
        """Record one adjudicated campaign outcome for an actor (Phase 1)."""
        rank = self._STAGE_RANK.get(str(max_stage), 0)
        self._actors[str(actor_id)].observations.append((float(asof), bool(is_attack), rank))

    def prior_campaign(self, actor_id: str, asof: float) -> str:
        """Return the prior-campaign category for an actor as of ``asof``.

        Only observations strictly before ``asof`` are considered.
        """
        rec = self._actors.get(str(actor_id))
        if not rec:
            return PRIOR_UNKNOWN
        past = [o for o in rec.observations if o[0] < float(asof)]
        if not past:
            return PRIOR_UNKNOWN
        attacks = [o for o in past if o[1]]
        if not attacks:
            return PRIOR_BENIGN
        reached_late = any(o[2] >= self._STAGE_RANK["CONTROL"] for o in attacks)
        return PRIOR_ATTACK_LATE if reached_late else PRIOR_ATTACK_EARLY

    def known_actor_count(self) -> int:
        return len(self._actors)

    def save_json(self, path) -> None:
        import json
        from pathlib import Path
        data = {a: r.observations for a, r in self._actors.items()}
        Path(path).write_text(json.dumps(data, indent=2) + "\n")

    @classmethod
    def load_json(cls, path) -> "CampaignMemory":
        import json
        from pathlib import Path
        mem = cls()
        p = Path(path)
        if p.exists():
            for actor, obs in json.loads(p.read_text()).items():
                mem._actors[actor].observations = [tuple(o) for o in obs]
        return mem


class Neo4jCampaignMemory:
    """Neo4j-backed campaign memory for the live SPHERE experiment.

    Schema (written only from adjudicated past episodes):
        (:Actor {actor_id})
        (:Actor)-[:HAD_CAMPAIGN]->(:CampaignObservation {asof_ts, is_attack, max_stage_rank})

    The read enforces ``asof_ts < $cutoff`` so Phase-2 decisions never see their
    own or future intelligence.
    """

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j", population: str = "default"):
        from neo4j import GraphDatabase
        self._driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=15)
        # Community Edition has only the single `neo4j` database, so train/test
        # populations coexist in it, separated by a `population` property rather
        # than by distinct databases (which require Enterprise).
        self.database = database
        self.population = population

    def close(self) -> None:
        self._driver.close()

    def record_campaign(self, actor_id: str, is_attack: bool, max_stage: str, asof_ts: str) -> None:
        rank = CampaignMemory._STAGE_RANK.get(str(max_stage), 0)
        query = """
        MERGE (a:Actor {actor_id:$actor_id, population:$pop})
        CREATE (c:CampaignObservation {asof_ts:$asof_ts, is_attack:$is_attack, max_stage_rank:$rank, population:$pop})
        MERGE (a)-[:HAD_CAMPAIGN]->(c)
        """
        with self._driver.session(database=self.database) as s:
            s.run(query, actor_id=str(actor_id), asof_ts=str(asof_ts), pop=self.population,
                  is_attack=bool(is_attack), rank=int(rank)).consume()

    def prior_campaign(self, actor_id: str, cutoff_ts: str) -> str:
        query = """
        MATCH (a:Actor {actor_id:$actor_id, population:$pop})-[:HAD_CAMPAIGN]->(c:CampaignObservation)
        WHERE c.asof_ts < $cutoff
        RETURN sum(CASE WHEN c.is_attack THEN 1 ELSE 0 END) AS attacks,
               count(c) AS total,
               max(CASE WHEN c.is_attack THEN c.max_stage_rank ELSE 0 END) AS max_rank
        """
        with self._driver.session(database=self.database) as s:
            row = s.run(query, actor_id=str(actor_id), cutoff=str(cutoff_ts), pop=self.population).single()
        if not row or not row["total"]:
            return PRIOR_UNKNOWN
        if not row["attacks"]:
            return PRIOR_BENIGN
        return PRIOR_ATTACK_LATE if (row["max_rank"] or 0) >= CampaignMemory._STAGE_RANK["CONTROL"] else PRIOR_ATTACK_EARLY
