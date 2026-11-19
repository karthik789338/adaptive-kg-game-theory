#!/usr/bin/env python3
"""EC-POMDG 3D.1C: audited *static* semantic bridge assertions on existing Neo4j.

By default --dry-run makes no graph changes. --apply is explicit and requires
EC_POMDG_BRIDGE_APPLY=YES; --verify is read-only. No IEC-104 or network activity.
The original 6742 :KGNode records and 33630 KGNode-to-KGNode relationships
are fingerprinted before/after any write and never modified by this code.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase, READ_ACCESS, WRITE_ACCESS

HOME = Path.home()
DEFAULT_BASE = HOME / 'ecpomdg_setup/dynamic_knowledge_graph'
DEFAULT_OUT = HOME / 'ecpomdg_audit/dynamic_knowledge_graph'
NS = {'general_cyber', 'power_grid_ics', 'component_topology'}


def ensure(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(',', ':'), default=str).encode('utf-8')


def read_plan(manifest_file: Path, attestation_file: Path) -> tuple[dict, dict, str, str]:
    plan_bytes = manifest_file.read_bytes()
    att_bytes = attestation_file.read_bytes()
    plan, att = json.loads(plan_bytes), json.loads(att_bytes)
    manifest_sha, att_sha = sha_bytes(plan_bytes), sha_bytes(att_bytes)
    ensure(plan['schema_version'] == 'ecpomdg.semantic_bridges.v1', 'Invalid bridge manifest version')
    ensure(att['schema_version'] == 'ecpomdg.semantic_bridge_attestation.v1', 'Invalid attestation version')
    ensure(att['manifest_sha256'] == manifest_sha, 'Attestation does not belong to this manifest')
    ensure(plan['original_kg_counts'] == {'nodes': 6742, 'relationships': 33630}, 'Frozen base counts unexpected')
    records = plan['bridge_assertions']
    ensure(len(records) == 5 and len({x['bridge_id'] for x in records}) == 5,
           'The 5 bridge assertion identities are not unique')
    ensure(plan['unapproved_general_cyber_mappings']['approved_count'] == 0,
           'General Cyber requires independent semantic review')
    for item in records:
        ensure(item['bridge_id'].startswith('ecpomdg.bridge.v1.'), 'Unexpected bridge ID')
        ensure(item['source_uid'].startswith('component_topology::') and
               item['target_uid'].startswith('power_grid_ics::'),
               'Only approved Topology-to-ICS bridges allowed in this phase')
        ensure(item['relation'].startswith('CALIBRATED_'), 'Must be calibration-scope bridge')
        ensure(len(item['evidence_keys']) > 0 and all(
               att['verified_evidence_keys'].get(k) is True for k in item['evidence_keys']),
               f'Missing verified evidence for {item["bridge_id"]}')
        ensure(item['meaning'].strip(), 'Bridge needs explicit bounded semantics')
    masks = plan['ablation_feature_masks']
    ensure(len(masks) == 8 and len({x['name'] for x in masks}) == 8,
           'Incomplete 2^3 KG ablation plan')
    ensure(all(set(m['kg_namespaces']) <= NS for m in masks), 'Unknown KG namespace')
    return plan, att, manifest_sha, att_sha


def read_rows(driver, statement: str, **params) -> list[dict]:
    with driver.session(database='neo4j', default_access_mode=READ_ACCESS) as session:
        return session.execute_read(
            lambda tx: [rec.data() for rec in tx.run(statement, **params)])


def fingerprint_original(driver) -> dict[str, Any]:
    nodes = read_rows(driver,
        'MATCH (n:KGNode) RETURN n.kg_uid AS uid, n.kg_record_sha256 AS digest ORDER BY uid')
    ensure(len(nodes) >= 6742, f'Frozen node count below original: {len(nodes)}')
    ensure(all(row['uid'] and row['digest'] for row in nodes), 'Missing frozen node UID/hash')
    ensure(len({row['uid'] for row in nodes}) == len(nodes), 'Duplicate frozen kg_uid')
    node_digest = sha_bytes(b'\n'.join(stable(row) for row in nodes))
    edges = read_rows(driver,
        'MATCH (a:KGNode)-[r]->(b:KGNode) '
        'RETURN a.kg_uid AS source, type(r) AS relation, b.kg_uid AS target, '
        'properties(r) AS attributes')
    ensure(len(edges) >= 33630, f'Frozen edge count below original: {len(edges)}')
    edge_enc = sorted(stable(row) for row in edges)
    edge_digest = sha_bytes(b'\n'.join(edge_enc))
    return {'frozen_nodes': len(nodes), 'frozen_relationships': len(edges),
            'node_fingerprint_sha256': node_digest,
            'relationship_fingerprint_sha256': edge_digest}


def validate_anchors(driver, plan: dict) -> list[dict]:
    details = []
    for item in plan['bridge_assertions']:
        results = read_rows(driver,
            'MATCH (s:KGNode {kg_uid:$source}) MATCH (t:KGNode {kg_uid:$target}) '
            'RETURN s.id AS source_id, s.role AS source_role, '
            's.physical_grid_connected AS physical_grid_connected, '
            's.kg_namespace AS source_ns, t.id AS target_id, '
            't.kg_namespace AS target_ns, t.name AS behavior_name',
            source=item['source_uid'], target=item['target_uid'])
        ensure(len(results) == 1, f'Missing/nonunique frozen bridge anchors for {item["bridge_id"]}')
        d = results[0]
        ensure(d['source_ns'] == 'component_topology' and d['target_ns'] == 'power_grid_ics',
               f'KG namespace mismatch {item["bridge_id"]}')
        if d['source_id'] == 'ASSET::controller':
            ensure(d['source_role'] == 'real_controller' and d['physical_grid_connected'] is True,
                   'Real controller physical trust mapping invalid')
        elif d['source_id'] == 'ASSET::decoy':
            ensure(d['source_role'] == 'decoy_controller' and d['physical_grid_connected'] is False,
                   'Decoy physical trust mapping invalid')
        else:
            raise RuntimeError('Unsupported source asset')
        details.append({'bridge_id': item['bridge_id'], **d})
    return details


def get_existing(driver) -> dict[str, dict]:
    items = read_rows(driver,
        'MATCH (b:ECBridgeAssertion) '
        'WHERE b.bridge_id STARTS WITH "ecpomdg.bridge.v1." '
        'OPTIONAL MATCH (b)-[:BRIDGE_FROM]->(s:KGNode) '
        'OPTIONAL MATCH (b)-[:BRIDGE_TO]->(t:KGNode) '
        'RETURN b.bridge_id AS bridge_id, b.source_uid AS source_uid, '
        'b.target_uid AS target_uid, b.relation AS relation, '
        'b.manifest_sha256 AS manifest_sha256, b.attestation_sha256 AS attestation_sha256, '
        'collect(DISTINCT s.kg_uid) AS source_refs, '
        'collect(DISTINCT t.kg_uid) AS target_refs')
    return {r['bridge_id']: r for r in items}


def validate_existing(existing: dict, plan: dict, manifest_sha: str, att_sha: str) -> None:
    planned = {b['bridge_id']: b for b in plan['bridge_assertions']}
    ensure(set(existing) <= set(planned), 'Unexpected prior v1 bridges: fail closed')
    for key, item in existing.items():
        b = planned[key]
        ensure(item['source_uid'] == b['source_uid'] and item['target_uid'] == b['target_uid']
               and item['relation'] == b['relation'] and
               item['manifest_sha256'] == manifest_sha and
               item['attestation_sha256'] == att_sha,
               f'Conflicting existing bridge metadata: {key}')
        ensure(item['source_refs'] == [b['source_uid']] and item['target_refs'] == [b['target_uid']],
               f'Conflicting or missing bridge endpoint links: {key}')


def write_approved(tx, bridges: list[dict], manifest_sha: str, att_sha: str) -> None:
    for item in bridges:
        rec = tx.run('''
            MATCH (s:KGNode {kg_uid:$source_uid})
            MATCH (t:KGNode {kg_uid:$target_uid})
            MERGE (b:ECBridgeAssertion {bridge_id:$bridge_id})
            ON CREATE SET
                b.phase = '3D.1C',
                b.schema_version = 'ecpomdg.semantic_bridges.v1',
                b.relation = $relation,
                b.meaning = $meaning,
                b.evidence_keys = $evidence_keys,
                b.source_uid = $source_uid,
                b.target_uid = $target_uid,
                b.manifest_sha256 = $manifest_sha,
                b.attestation_sha256 = $att_sha,
                b.evidence_scope = 'PRIOR_FROZEN_LAB_CALIBRATION_ONLY',
                b.is_attack_assertion = false,
                b.is_live_event = false,
                b.created_at_utc = toString(datetime.realtime())
            MERGE (b)-[:BRIDGE_FROM]->(s)
            MERGE (b)-[:BRIDGE_TO]->(t)
            RETURN b.bridge_id AS id
            ''', bridge_id=item['bridge_id'], source_uid=item['source_uid'],
                 target_uid=item['target_uid'], relation=item['relation'],
                 meaning=item['meaning'], evidence_keys=item['evidence_keys'],
                 manifest_sha=manifest_sha, att_sha=att_sha).single()
        ensure(rec is not None and rec['id'] == item['bridge_id'], 'Bridge write/anchor missing')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--dry-run', action='store_true')
    choice.add_argument('--apply', action='store_true')
    choice.add_argument('--verify', action='store_true')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_BASE / 'phase3d1c_semantic_bridge_manifest.json')
    parser.add_argument('--attestation', type=Path, default=DEFAULT_BASE / 'phase3d1c_calibration_evidence_attestation.json')
    parser.add_argument('--out-dir', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    mode = 'apply' if args.apply else 'verify' if args.verify else 'dry_run'
    ensure(not args.apply or os.environ.get('EC_POMDG_BRIDGE_APPLY') == 'YES',
           'Apply blocked. Explicitly set EC_POMDG_BRIDGE_APPLY=YES to permit five bridge writes.')
    plan, att, manifest_sha, att_sha = read_plan(args.manifest, args.attestation)
    user = os.environ.get('NEO4J_USER', 'neo4j')
    password = os.environ.get('NEO4J_PASSWORD') or getpass.getpass('Neo4j password: ')
    driver = GraphDatabase.driver('bolt://127.0.0.1:7687', auth=(user, password))
    try:
        driver.verify_connectivity()
        baseline = fingerprint_original(driver)
        anchors = validate_anchors(driver, plan)
        existing = get_existing(driver)
        validate_existing(existing, plan, manifest_sha, att_sha)
        print('FROZEN_6742_NODES_AND_33630_RELATIONSHIPS: PASS', flush=True)
        print('FROZEN_BASELINE_PROPERTY_AND_EDGE_FINGERPRINT: CAPTURED', flush=True)
        print('FIVE_EVIDENCE_ATTESTED_TOPOLOGY_ICS_BRIDGES: PASS', flush=True)
        print('GENERAL_CYBER_BRIDGES_APPROVED: 0', flush=True)
        print('ABLATED_KG_FEATURE_MASKS: 8', flush=True)
        if args.apply:
            with driver.session(database='neo4j', default_access_mode=WRITE_ACCESS) as session:
                session.execute_write(write_approved, plan['bridge_assertions'], manifest_sha, att_sha)
            print('APPROVED_BRIDGE_ASSERTIONS_APPLIED: 5', flush=True)
        after = fingerprint_original(driver)
        ensure(after == baseline, 'CRITICAL: frozen KG fingerprints changed!')
        final = get_existing(driver)
        validate_existing(final, plan, manifest_sha, att_sha)
        if args.apply or args.verify:
            ensure(len(final) == 5, f'Expected exactly five installed bridges; found {len(final)}')
        bridge_edges = read_rows(driver,
            'MATCH (b:ECBridgeAssertion) WHERE b.bridge_id STARTS WITH "ecpomdg.bridge.v1." '
            'MATCH (b)-[r]->(n:KGNode) RETURN type(r) AS kind, count(*) AS count '
            'ORDER BY kind')
        ensure(all(x['kind'] in {'BRIDGE_FROM', 'BRIDGE_TO'} for x in bridge_edges),
               'Unrecognized bridge-to-KG relationship')
        if args.apply or args.verify:
            ensure({x['kind']: x['count'] for x in bridge_edges} ==
                   {'BRIDGE_FROM': 5, 'BRIDGE_TO': 5},
                   'Not exactly ten expected bridge endpoint relationships')
        report = {
            'phase': '3D.1C', 'mode': mode, 'source_graph_modifications': 0,
            'original_kg_baseline': baseline, 'post_operation_original_kg': after,
            'manifest_sha256': manifest_sha, 'evidence_attestation_sha256': att_sha,
            'validated_anchor_pairs': anchors,
            'bridge_assertions_installed': len(final), 'bridge_endpoint_relationships': bridge_edges,
            'general_cyber_bridges_approved': 0,
            'cross_graph_kg_to_kg_edges_created': 0,
            'static_calibration_bridges_only': True,
            'live_episode_graph_update_performed': False,
            'dynamic_kg_causal_effect_proven': False,
            'ablation_feature_masks': plan['ablation_feature_masks'],
            'notes': [
                'Bridges are separate assertion nodes; no direct KGNode-to-KGNode edges are added.',
                'Only prior independent calibration evidence was used to justify static capabilities.',
                'General-to-ICS mapping requires a future separately reviewed ontology alignment.',
                'Static and dynamic comparisons must start from the same fixed bridge set.',
            ],
        }
        args.out_dir.mkdir(parents=True, exist_ok=True)
        dest = args.out_dir / f'phase3d1c_neo4j_semantic_bridges_{mode}.json'
        dest.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + '\n')
        print('FROZEN_CORE_CRYPTOGRAPHICALLY_UNCHANGED: PASS', flush=True)
        print('CURRENT_APPROVED_BRIDGE_COUNT:', len(final), flush=True)
        print('CURRENT_BRIDGE_ENDPOINT_RELATIONSHIP_COUNT:', sum(x['count'] for x in bridge_edges), flush=True)
        print('DIRECT_FROZEN_CROSS_GRAPH_EDGES_CREATED: 0', flush=True)
        print('PHASE3D1C_SEMANTIC_BRIDGES_' + mode.upper() + ': PASS', flush=True)
        print('OUTPUT:', dest)
    finally:
        driver.close()


if __name__ == '__main__':
    main()
