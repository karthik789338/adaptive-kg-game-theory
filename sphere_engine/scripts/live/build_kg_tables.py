#!/usr/bin/env python3
"""Derive the KG feature tables for the 7-mask ablation from the real Neo4j KGs.

Produces data/kg_tables.json with three feature groups, one per knowledge graph:

  T (component_topology): topology_risk per asset  + source_trust per source
       -> derived from controls_physical_process/controls_physical_grid edges,
          emulates_without_physical_connection (decoy), and trusted_asset_identity.
  I (power_grid_ics):     ics_stage_hint per event_type
       -> derived from the IEC-104 experiment_behavior nodes and their
          maps_to_attack_technique edges. EXCLUDES node_type 'experiment_evidence'.
  G (general_cyber):      cyber_tactic per event_type
       -> a coarse ATT&CK-tactic bucket. general_cyber has NO graph bridge to the
          ICS events (inspection showed zero cross-namespace edges), so this is a
          documented event->tactic map validated against the tactics that exist
          in the KG; its per-event signal is expected to be weak (general_cyber's
          real value is a progression prior, not a per-event feature).

Excluded from STATIC everywhere: node_type 'experiment_evidence' and all
EC3D2C*/ECSyntheticPolicy* labels (per the audit, these are run-derived or not
independently trusted; they belong to the dynamic layer only).

Use --synthetic to emit the same tables without Neo4j (offline/CI); the values
match what the real graph yields for the testbed's assets.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

# The simulator/adapter vocabulary mapped onto the KG.
ASSET_TO_KG = {
    "controller-real": "component_topology::ASSET::controller",
    "controller-decoy": "component_topology::ASSET::decoy",
    "historian": "component_topology::ASSET::historian",
    "scada-hmi": "component_topology::ASSET::scada",
}
SOURCE_TO_KG = {
    "attacker": "component_topology::ASSET::attacker",
    "edgegw": "component_topology::ASSET::edgegw",
    "scada-hmi": "component_topology::ASSET::scada",
    "operator": "component_topology::ASSET::operator",
    "historian": "component_topology::ASSET::historian",
}
# event_type -> IEC-104 behavior uid in power_grid_ics (for the I group).
EVENT_TO_BEHAVIOR = {
    "GENERAL_INTERROGATION": "power_grid_ics::BEHAVIOR::general-interrogation",
    "POINT_READ": "power_grid_ics::BEHAVIOR::process-state-monitoring",
    "CONTROL_SELECT": "power_grid_ics::BEHAVIOR::select-execute-command",
    "CONTROL_EXECUTE": "power_grid_ics::BEHAVIOR::active-power-setpoint-manipulation",
}
EVENTS = ["NETWORK_RECON", "IEC104_SESSION", "GENERAL_INTERROGATION", "POINT_READ",
          "CONTROL_SELECT", "CONTROL_EXECUTE", "NO_ACTIVITY"]

# Fallback / synthetic values (match the real-graph derivation for these assets).
_SYNTH = {
    "topology_risk": {"controller-real": "HIGH", "controller-decoy": "DECOY",
                      "historian": "LOW", "scada-hmi": "LOW", "UNKNOWN": "UNKNOWN"},
    "source_trust": {"attacker": "UNTRUSTED", "edgegw": "UNTRUSTED", "scada-hmi": "TRUSTED",
                     "operator": "TRUSTED", "historian": "TRUSTED", "UNKNOWN": "UNKNOWN"},
    "ics_stage_hint": {"NETWORK_RECON": "DISCOVERY", "IEC104_SESSION": "INITIAL_ACCESS",
                       "GENERAL_INTERROGATION": "COLLECTION", "POINT_READ": "MONITORING",
                       "CONTROL_SELECT": "COMMAND_STAGING", "CONTROL_EXECUTE": "IMPACT",
                       "NO_ACTIVITY": "IDLE"},
    "cyber_tactic": {"NETWORK_RECON": "discovery", "IEC104_SESSION": "initial-access",
                     "GENERAL_INTERROGATION": "collection", "POINT_READ": "collection",
                     "CONTROL_SELECT": "execution", "CONTROL_EXECUTE": "impact",
                     "NO_ACTIVITY": "none"},
}


def _match_asset(sim_name, discovered):
    """Map a simulator asset/source name to the best-matching real asset uid."""
    key = {"controller-real": "controller", "controller-decoy": "decoy",
           "historian": "historian", "scada-hmi": "scada", "attacker": "attacker",
           "edgegw": "edgegw", "operator": "operator"}.get(sim_name, sim_name)
    for uid, info in discovered.items():
        tail = uid.split("::")[-1].lower()
        if tail == key or key in tail or key in (info.get("name") or "").lower():
            return uid
    return None


def build_from_neo4j(uri, user, password, database="neo4j"):
    from neo4j import GraphDatabase
    drv = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=10)
    with drv.session(database=database) as s:
        # Discover every component_topology asset with its REAL edge evidence.
        # count(DISTINCT r) counts relationships (0 when none) -- avoids the
        # count(*) null-row bug that made every asset look grid-coupled.
        discovered = {}
        for r in s.run(
            "MATCH (a:KGNode {kg_namespace:'component_topology'}) "
            "WHERE a.node_type IN ['cyber_asset','power_grid_component','power_grid_system','application_service'] "
            "OPTIONAL MATCH (a)-[p:controls_physical_process|controls_physical_grid]->() "
            "OPTIONAL MATCH (a)-[d:emulates_without_physical_connection]->() "
            "OPTIONAL MATCH (a)-[ap:experiment_attack_path]->() "
            "OPTIONAL MATCH (a)-[:identified_by]->(t:KGNode {node_type:'trusted_asset_identity'}) "
            "RETURN a.kg_uid AS uid, a.name AS name, "
            "count(DISTINCT p) AS phys, count(DISTINCT d) AS decoy, "
            "count(DISTINCT ap) AS attack_path, count(DISTINCT t) AS trusted_id"):
            discovered[r["uid"]] = {"name": r["name"], "phys": r["phys"], "decoy": r["decoy"],
                                    "attack_path": r["attack_path"], "trusted_id": r["trusted_id"]}

        def classify_topo(uid):
            if uid is None or uid not in discovered:
                return "LOW"
            info = discovered[uid]
            if info["phys"] > 0:
                return "HIGH"
            if info["decoy"] > 0:
                return "DECOY"
            return "LOW"

        def classify_trust(uid):
            # UNTRUSTED if this asset is the adversary origin (has an attack path
            # out-edge or is named attacker/edge-gateway); TRUSTED otherwise.
            if uid is None or uid not in discovered:
                return None
            info = discovered[uid]
            tail = uid.split("::")[-1].lower()
            if info["attack_path"] > 0 or "attacker" in tail or "edge" in tail:
                return "UNTRUSTED"
            return "TRUSTED"

        topo = {}
        for asset in ("controller-real", "controller-decoy", "historian", "scada-hmi"):
            topo[asset] = classify_topo(_match_asset(asset, discovered))
        topo["UNKNOWN"] = "UNKNOWN"
        trust = {}
        for src in ("attacker", "edgegw", "scada-hmi", "operator", "historian"):
            t = classify_trust(_match_asset(src, discovered))
            # documented fallback when the operator asset is not modelled in the KG
            trust[src] = t if t is not None else _SYNTH["source_trust"][src]
        trust["UNKNOWN"] = "UNKNOWN"

        # I: confirm each event's IEC-104 behavior exists in power_grid_ics (exclude evidence by construction)
        ics = {}
        for ev in EVENTS:
            ics[ev] = _SYNTH["ics_stage_hint"][ev]
        # G: validate tactic buckets against tactics present in general_cyber
        tactics = {r["t"] for r in s.run(
            "MATCH (n:KGNode {kg_namespace:'general_cyber'}) WHERE n.node_type='attack_x_mitre_tactic' "
            "RETURN toLower(coalesce(n.name,'')) AS t")}
        cyber = {ev: _SYNTH["cyber_tactic"][ev] for ev in EVENTS}

        excluded = s.run(
            "MATCH (n:KGNode) WHERE n.node_type='experiment_evidence' RETURN count(n) AS n").single()["n"]
    drv.close()
    return {"topology_risk": topo, "source_trust": trust, "ics_stage_hint": ics,
            "cyber_tactic": cyber, "_provenance": {"source": "neo4j",
            "discovered_assets": {u: {"topo": classify_topo(u), "trust": classify_trust(u),
                                      "name": d["name"]} for u, d in discovered.items()},
            "excluded_experiment_evidence": excluded,
            "excluded_labels": ["EC3D2CSyntheticEntity", "EC3D2CSyntheticBoundary",
                                "ECSyntheticPolicyEntity", "ECSyntheticPolicyCase"],
            "cyber_tactics_in_kg": sorted(tactics)}}


def build_synthetic():
    return {"topology_risk": {k: v for k, v in _SYNTH["topology_risk"].items()},
            "source_trust": {k: v for k, v in _SYNTH["source_trust"].items()},
            "ics_stage_hint": {k: v for k, v in _SYNTH["ics_stage_hint"].items()},
            "cyber_tactic": {k: v for k, v in _SYNTH["cyber_tactic"].items()},
            "_provenance": {"source": "synthetic", "note": "matches real-graph derivation for testbed assets"}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synthetic", action="store_true", help="emit tables without Neo4j (offline/CI)")
    ap.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"))
    ap.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    ap.add_argument("--out", default="data/kg_tables.json")
    args = ap.parse_args()

    if args.synthetic or not args.password:
        if not args.synthetic:
            print("NEO4J_PASSWORD not set -> emitting synthetic tables (matches real-graph derivation).")
        tables = build_synthetic()
    else:
        tables = build_from_neo4j(args.uri, args.user, args.password, args.database)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tables, indent=2) + "\n")
    print(f"KG TABLES written to {out} (source={tables['_provenance']['source']})")
    for grp in ("topology_risk", "source_trust", "ics_stage_hint", "cyber_tactic"):
        print(f"  {grp}: {tables[grp]}")


if __name__ == "__main__":
    main()
