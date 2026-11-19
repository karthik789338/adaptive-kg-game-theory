#!/usr/bin/env python3
from __future__ import annotations
import argparse
import os

from neo4j import GraphDatabase

SCHEMA = [
    "CREATE CONSTRAINT episode_id IF NOT EXISTS FOR (n:Episode) REQUIRE n.episode_id IS UNIQUE",
    "CREATE CONSTRAINT runtime_event_id IF NOT EXISTS FOR (n:RuntimeObservation) REQUIRE n.event_id IS UNIQUE",
    "CREATE CONSTRAINT stage_name IF NOT EXISTS FOR (n:AttackStage) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT semantic_event_type IF NOT EXISTS FOR (n:EventSemantic) REQUIRE n.event_type IS UNIQUE",
]
STAGES = ["RECON", "ACCESS", "DER_ENUM", "CONTROL", "IMPACT"]
SEMANTICS = {
    "NETWORK_RECON": "RECON",
    "iec104_connection_request": "ACCESS",
    "iec104_session_established": "ACCESS",
    "iec104_interrogation": "DER_ENUM",
    "iec104_point_read": "DER_ENUM",
    "iec104_select": "CONTROL",
    "iec104_execute": "IMPACT",
}

parser = argparse.ArgumentParser()
parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"))
parser.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD"))
args = parser.parse_args()
if not args.password:
    raise SystemExit("Set NEO4J_PASSWORD or pass --password")

driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
with driver.session() as session:
    for statement in SCHEMA:
        session.run(statement).consume()
    for stage in STAGES:
        session.run("MERGE (:AttackStage {name:$name})", name=stage).consume()
    for event_type, stage in SEMANTICS.items():
        session.run("""
        MERGE (e:EventSemantic {event_type:$event_type})
        MATCH (s:AttackStage {name:$stage})
        MERGE (e)-[:SUPPORTS_STAGE]->(s)
        """, event_type=event_type, stage=stage).consume()
driver.close()
print("NEO4J_FINAL_SCHEMA: PASS")
