#!/usr/bin/env python3
"""Phase 3D.2A server-side online ingestion/readback on SPHERE 'kg'.

Called synchronously by a live coordinator AFTER authentic trusted IEC104 SELECT
but BEFORE computing the post-SELECT defender action. Separate overlay only.
The caller NEVER passes defender action, hidden stage, outcome, or plant state.
A successful return proves commit/query ordering, NOT efficacy of dynamic KGs.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import getpass
import hashlib
import json
import os
from pathlib import Path
import re

from neo4j import GraphDatabase, WRITE_ACCESS
from manage_phase3d1d_neo4j_episode_observations import (
    SOURCE_UID, BEHAVIORS, ALLOWED, EXCLUDED, check_freeze,
    validate_anchors, guard_cross_episode_reuse, read_existing,
)
from manage_phase3d1c_neo4j_semantic_bridges import get_existing
from audit_phase3d1e_neo4j_asof_feature_paths import (
    MASKS, summarize_asof, utc,
)

BASE = Path.home() / 'ecpomdg_setup' / 'dynamic_knowledge_graph'
OUT = Path.home() / 'ecpomdg_audit' / 'dynamic_knowledge_graph' / 'online_ingestion'
SCHEMA = 'ecpomdg.online_observations.v1'
EXPECTED_REAL = 'asset-field-001'


def require(ok: bool, why: str):
    if not ok:
        raise ValueError(why)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def validate_payload(data: dict):
    expected = {'schema_version', 'episode_id', 'observation_count',
                'source_event_ids', 'select_event_id', 'asof_cutoff_utc',
                'trusted_observation_source', 'trusted_asset_id',
                'online_ingestion_requested', 'observations'}
    require(set(data) == expected, 'Payload includes missing/forbidden fields')
    require(data['schema_version'] == SCHEMA and data['online_ingestion_requested'] is True,
            'Incorrect schema or online ingestion flag')
    episode = data['episode_id']
    require(isinstance(episode, str) and re.fullmatch(r'\d{8}T\d{12}Z', episode) and episode not in EXCLUDED,
            'Invalid or previously calibrated episode ID')
    require(data['trusted_asset_id'] == EXPECTED_REAL and
            data['trusted_observation_source'] == 'fresh_defender_operational_api',
            'Untrusted evidence source')
    require(type(data['observation_count']) is int and
            5 <= data['observation_count'] <= 100 and
            len(data['observations']) == data['observation_count'],
            'Invalid event count')
    canonical = data['source_event_ids']
    require(len(canonical) == 5 and len(set(canonical)) == 5 and
            canonical[-1] == data['select_event_id'], 'Bad canonical source ids')
    cutoff = utc(data['asof_cutoff_utc'])
    require(cutoff <= datetime.now(timezone.utc) + timedelta(seconds=15),
            'Unrealistic future cutoff')
    seen, selected, gis, reads, conn, sessions = set(), [], [], [], [], []
    for e in data['observations']:
        require(set(e) == {'event_id', 'event_type', 'observed_at_utc',
                           'trusted_asset_id', 'asset_uid', 'behavior_uid',
                           'ioa', 'command_phase', 'canonical_source'},
                'Observation contains prohibited extra fields')
        eid = e['event_id']
        require(isinstance(eid, str) and 3 <= len(eid) <= 128 and eid not in seen,
                'Duplicate/invalid event id')
        seen.add(eid)
        kind = e['event_type']
        require(kind in ALLOWED and e['trusted_asset_id'] == EXPECTED_REAL and
                e['asset_uid'] == SOURCE_UID and
                e['behavior_uid'] == BEHAVIORS.get(kind),
                'Invalid observed behavior/asset')
        t = utc(e['observed_at_utc'])
        require(t <= cutoff, 'Future event included in predecision snapshot')
        require(e['canonical_source'] is (eid in canonical),
                'Untrusted canonical source marking')
        if kind == 'iec104_point_read':
            require(type(e['ioa']) is int and e['ioa'] in (11,12,13) and
                    e['command_phase'] is None, 'Invalid point read')
            reads.append(e)
        elif kind == 'iec104_select':
            require(eid == data['select_event_id'] and
                    e['ioa'] == 100 and e['command_phase'] == 'select',
                    'Unsupported SELECT metadata')
            selected.append(e)
        else:
            require(e['ioa'] is None and e['command_phase'] is None,
                    'Unexpected command details')
            if kind == 'iec104_connection_request': conn.append(e)
            if kind == 'iec104_session_established': sessions.append(e)
            if kind == 'iec104_interrogation': gis.append(e)
    require(set(canonical) <= seen and len(selected) == 1,
            'Missing canonical or ambiguous SELECT')
    select_time = utc(selected[0]['observed_at_utc'])
    require(conn and sessions and gis and
            min(utc(x['observed_at_utc']) for x in conn) <
            min(utc(x['observed_at_utc']) for x in sessions) <
            min(utc(x['observed_at_utc']) for x in gis) < select_time,
            'Connection/session/GI/select sequence invalid')
    require({x['ioa'] for x in reads} == {11,12,13} and
            all(utc(x['observed_at_utc']) < select_time for x in reads),
            'DER point reads not completely before SELECT')
    return data


def expected_rows(data, sha):
    return [{
        'event_key': f"ecpomdg.online.observation.v1.{data['episode_id']}.{e['event_id']}",
        'event_id': e['event_id'], 'episode_id': data['episode_id'],
        'event_type': e['event_type'], 'observed_at_utc': e['observed_at_utc'],
        'source_uid': e['asset_uid'], 'behavior_uid': e['behavior_uid'],
        'ioa': e['ioa'], 'command_phase': e['command_phase'],
        'canonical_source': e['canonical_source'], 'snapshot_sha256': sha,
    } for e in data['observations']]


def ingest_tx(tx, data, rows, sha):
    ep = data['episode_id']
    # No replays: do not overwrite an episode written by another invocation.
    existing = tx.run('MATCH (e:ECEpisode {episode_id:$id}) RETURN count(e) AS n', id=ep).single()['n']
    require(existing == 0, 'Episode id already exists; no overwrite')
    tx.run('''
      CREATE (e:ECEpisode {
        episode_id:$id, snapshot_sha256:$sha,
        decision_cutoff_utc:$cutoff, observation_count:$count,
        online_ingestion:true, post_hoc_replay:false,
        schema_version:'ecpomdg.online_observations.v1'
      })
    ''', id=ep, sha=sha, cutoff=data['asof_cutoff_utc'], count=len(rows)).consume()
    for row in rows:
        rec = tx.run('''
          MATCH (e:ECEpisode {episode_id:$ep})
          MATCH (a:KGNode {kg_uid:$source})
          OPTIONAL MATCH (b:KGNode {kg_uid:$behavior})
          CREATE (o:ECObservation {
            event_key:$key, source_event_id:$event_id,
            episode_id:$ep, event_type:$kind,
            observed_at_utc:$observed, source_uid:$source,
            behavior_uid:$behavior, ioa:$ioa, command_phase:$phase,
            canonical_source:$canonical, snapshot_sha256:$sha,
            trusted_collector_source:true, online_ingestion:true
          })
          CREATE (e)-[:HAS_OBSERVATION]->(o)
          CREATE (o)-[:OBSERVED_ON]->(a)
          FOREACH (_ IN CASE WHEN b IS NULL THEN [] ELSE [1] END |
            CREATE (o)-[:CLASSIFIED_AS]->(b))
          RETURN o.event_key AS key
        ''', ep=ep, key=row['event_key'], event_id=row['event_id'],
            kind=row['event_type'], observed=row['observed_at_utc'],
            source=row['source_uid'], behavior=row['behavior_uid'],
            ioa=row['ioa'], phase=row['command_phase'],
            canonical=row['canonical_source'], sha=sha).single()
        require(rec is not None and rec['key'] == row['event_key'], 'Incomplete event write')


def audit_rows(driver, data, sha):
    episodes, actual = read_existing(driver, data['episode_id'])
    require(len(episodes) == 1 and episodes[0] == {
        'episode_id': data['episode_id'], 'snapshot_sha256': sha,
        'decision_cutoff_utc': data['asof_cutoff_utc'],
        'observation_count': data['observation_count'],
        'online_ingestion': True,
    }, 'Online episode metadata mismatch')
    expected = expected_rows(data, sha)
    require(len(actual) == len(expected), 'Online observation count mismatch')
    by_key = {r['event_key']: r for r in actual}
    require(len(by_key) == len(actual), 'Duplicate graph events')
    for row in expected:
        got = by_key.get(row['event_key'])
        require(got is not None and all(got.get(k) == v for k,v in row.items()),
                'Online graph event fields mismatch')
        require(got['asset_refs'] == [row['source_uid']] and
                got['behavior_refs'] == ([row['behavior_uid']] if row['behavior_uid'] else []),
                'Online semantic links mismatch')
    return actual


def self_test():
    now = datetime.now(timezone.utc)
    ts = lambda dt: dt.isoformat()
    from datetime import timedelta
    original = [{'event_id':n, 'event_type':kind, 'observed_at_utc':ts(now+timedelta(milliseconds=i)),
                 'trusted_asset_id':EXPECTED_REAL, 'asset_uid':SOURCE_UID,
                 'behavior_uid':BEHAVIORS.get(kind), 'ioa':ioa,
                 'command_phase':'select' if kind=='iec104_select' else None,
                 'canonical_source':n in {'conn','sess','gi1','read11','select'}}
                for i, (n,kind,ioa) in enumerate([
                    ('conn','iec104_connection_request',None),
                    ('sess','iec104_session_established',None),
                    ('gi1','iec104_interrogation',None),
                    ('read11','iec104_point_read',11),
                    ('read12','iec104_point_read',12),
                    ('read13','iec104_point_read',13),
                    ('select','iec104_select',100)])]
    payload = dict(schema_version=SCHEMA, episode_id='20261014T183905999999Z',
                   observation_count=len(original), source_event_ids=['conn','sess','gi1','read11','select'],
                   select_event_id='select', asof_cutoff_utc=ts(now+timedelta(seconds=1)),
                   trusted_observation_source='fresh_defender_operational_api',
                   trusted_asset_id=EXPECTED_REAL, online_ingestion_requested=True,
                   observations=original)
    validate_payload(payload)
    import copy
    bad = copy.deepcopy(payload)
    bad['observations'][-1]['observed_at_utc']=ts(now+timedelta(seconds=2))
    try: validate_payload(bad)
    except ValueError: pass
    else: raise AssertionError('Future event accepted')
    bad=copy.deepcopy(payload); bad['oracle_stage']='CONTROL_MANIPULATION'
    try: validate_payload(bad)
    except ValueError: pass
    else: raise AssertionError('Oracle injection accepted')
    bad=copy.deepcopy(payload); bad['observations'][-1]['trusted_asset_id']='asset-field-002'
    try: validate_payload(bad)
    except ValueError: pass
    else: raise AssertionError('Decoy impersonation accepted')
    print('PHASE3D2A_ONLINE_INGESTION_CONTRACT_TESTS: PASS')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', type=Path)
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    require(args.snapshot is not None and args.snapshot.is_file(), 'Snapshot required')
    require(os.environ.get('EC_POMDG_ONLINE_GRAPH_COMMIT') == 'YES',
            'Explicit EC_POMDG_ONLINE_GRAPH_COMMIT=YES required')
    raw = args.snapshot.read_bytes()
    data = validate_payload(json.loads(raw))
    sha = hashlib.sha256(raw).hexdigest()
    pwd = os.environ.get('NEO4J_PASSWORD') or getpass.getpass('Neo4j password: ')
    driver = GraphDatabase.driver('bolt://127.0.0.1:7687',
                                  auth=(os.environ.get('NEO4J_USER','neo4j'),pwd))
    try:
        driver.verify_connectivity()
        baseline = check_freeze(driver, BASE / 'phase3d1c_semantic_bridge_manifest.json',
                                BASE / 'phase3d1c_calibration_evidence_attestation.json')
        validate_anchors(driver, data)
        guard_cross_episode_reuse(driver, data)
        # Atomic write+commit. No policy decision has yet been made by the caller.
        with driver.session(database='neo4j', default_access_mode=WRITE_ACCESS) as session:
            session.execute_write(ingest_tx, data, expected_rows(data, sha), sha)
        commit_at = now_utc()
        rows = audit_rows(driver, data, sha)
        existing_bridges = get_existing(driver)
        pairs = {(r['source_uid'],r['target_uid']) for r in existing_bridges.values()}
        require(len(pairs)==5, 'Approved bridge count changed')
        features = {mask:summarize_asof(rows,pairs,utc(data['asof_cutoff_utc']),namespaces)
                    for mask,namespaces in MASKS.items()}
        require(features['I_T']['iec104_select_visible'] is True and
                data['select_event_id'] in features['I_T']['source_event_ids_asof'],
                'Graph did not return live SELECT before decision')
        select_ics = 'power_grid_ics::BEHAVIOR::select-execute-command'
        require(any(r['event_id']==data['select_event_id'] and
                    r['behavior_refs']==[select_ics] and
                    r['asset_refs']==[SOURCE_UID] and
                    (SOURCE_UID,select_ics) in pairs for r in rows),
                'Online SELECT has no verified Topology–ICS path')
        require(check_freeze(driver, BASE / 'phase3d1c_semantic_bridge_manifest.json',
                             BASE / 'phase3d1c_calibration_evidence_attestation.json') == baseline,
                'Frozen KGs or approved bridges mutated')
        read_at = now_utc()
        OUT.mkdir(parents=True, exist_ok=True)
        report = dict(phase='3D.2A', episode_id=data['episode_id'],
                      snapshot_sha256=sha, event_count=len(rows),
                      select_event_id=data['select_event_id'],
                      snapshot_asof_cutoff_utc=data['asof_cutoff_utc'],
                      neo4j_write_committed_at_utc=commit_at,
                      neo4j_read_completed_at_utc=read_at,
                      features_by_mask=features,
                      online_graph_commit_and_query_completed=True,
                      frozen_kg_and_bridge_fingerprint_unchanged=True,
                      graph_features_used_for_bayesian_likelihood=False,
                      dynamic_kg_advantage_established=False,
                      no_network_level_redirection=True,
                      integration_diagnostic_not_heldout_efficacy=True)
        dest = OUT / f"{data['episode_id']}_online_graph_ingest_readback.json"
        require(not dest.exists(), 'Refuse to overwrite prior online audit report')
        dest.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
        print('FROZEN_KGS_AND_FIVE_BRIDGES_UNCHANGED: PASS')
        print('ONLINE_EPISODE_OBSERVATIONS_COMMITTED:',len(rows))
        print('ONLINE_GRAPH_READBACK_SELECT_BEFORE_DEFENDER_DECISION: PASS')
        for mask in MASKS:
            f=features[mask]
            print(f'{mask:8s} T_LINKED={f["topology_linked_observations"]:2d} '
                  f'I_LINKED={f["ics_linked_observations"]:2d} '
                  f'IT_BRIDGED={f["validated_topology_ics_bridge_observations"]:2d}')
        print('GRAPH_FEATURES_IN_BAYESIAN_LIKELIHOOD: NO')
        print('PHASE3D2A_ONLINE_GRAPH_COMMIT_AND_READ: PASS')
        print('OUTPUT:',dest)
    finally:
        driver.close()

if __name__=='__main__':
    main()
