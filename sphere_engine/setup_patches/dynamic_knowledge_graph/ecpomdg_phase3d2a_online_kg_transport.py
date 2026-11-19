#!/usr/bin/env python3
"""Synchronous SSH-based trusted observations -> KG server transaction+query.

Live experiment's last required real-controller operation is SELECT-only; the
coordinator invokes this module between trusted SELECT and defender decision.
No secrets are written to command lines or files. The password prompt runs on
kg's TTY inside a bounded SSH subprocess, not through telemetry records.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import shlex
import subprocess

REAL = 'asset-field-001'
REAL_UID = 'component_topology::ASSET::controller'
BEHAVIOR = {
    'iec104_interrogation': 'power_grid_ics::BEHAVIOR::general-interrogation',
    'iec104_point_read': 'power_grid_ics::BEHAVIOR::process-state-monitoring',
    'iec104_select': 'power_grid_ics::BEHAVIOR::select-execute-command',
}
ALLOWED = {'iec104_connection_request', 'iec104_session_established',
           'iec104_interrogation', 'iec104_point_read', 'iec104_select'}
SERVER_SCRIPT = ('$HOME/ecpomdg_setup/dynamic_knowledge_graph/'
                 'ingest_and_query_phase3d2a_live_neo4j_observations.py')
SERVER_INPUT = '~/ecpomdg_setup/dynamic_knowledge_graph'
SERVER_OUTPUT = '~/ecpomdg_audit/dynamic_knowledge_graph/online_ingestion'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def ts(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(t.tzinfo is not None, 'Timestamp requires timezone')
    return t.astimezone(timezone.utc)


def create_online_snapshot(run_id, trusted_rows, canonical_ids, select_event_id, decision_cutoff):
    require(re.fullmatch(r'\d{8}T\d{12}Z', run_id), 'Invalid run id')
    require(len(canonical_ids) == 5 and len(set(canonical_ids)) == 5 and
            canonical_ids[-1] == select_event_id, 'Canonical IDs invalid')
    cutoff = ts(decision_cutoff)
    require(trusted_rows and len(trusted_rows) <= 100,
            'Unexpected trusted API record volume; stop and inspect')
    rows = []
    seen = set()
    for row in trusted_rows:
        require(row.get('asset_id') == REAL and row.get('protocol') == 'IEC104',
                'Collector provided untrusted identity/protocol')
        eid = row.get('event_id')
        require(isinstance(eid,str) and 3 <= len(eid) <= 128 and eid not in seen,
                'Invalid/duplicate event ID')
        seen.add(eid)
        event_at = ts(row['collector_ts_utc'])
        require(event_at <= cutoff, 'Collector event beyond evidence snapshot cutoff')
        kind = row.get('event_type')
        require(kind != 'iec104_execute', 'Real execution present in fresh evidence')
        if kind not in ALLOWED:
            continue
        ioa = row.get('ioa') if kind in ('iec104_point_read', 'iec104_select') else None
        phase = 'select' if kind == 'iec104_select' else None
        if kind == 'iec104_point_read':
            require(type(ioa) is int and ioa in (11,12,13), 'Unrecognized read IOA')
        if kind == 'iec104_select':
            require(eid == select_event_id and ioa == 100 and
                    row.get('command_phase') == 'select' and
                    row.get('asdu_type') == 50 and row.get('cause') == 6 and
                    row.get('common_address') == 47 and
                    float(row.get('requested', -1)) == 200.0,
                    'Unrecognized SELECT evidence')
        rows.append(dict(event_id=eid, event_type=kind,
                         observed_at_utc=event_at.isoformat(),
                         trusted_asset_id=REAL, asset_uid=REAL_UID,
                         behavior_uid=BEHAVIOR.get(kind),
                         ioa=ioa, command_phase=phase,
                         canonical_source=eid in canonical_ids))
    require(len(rows) >= 5 and len(rows) <= 100 and
            set(canonical_ids) <= {r['event_id'] for r in rows},
            'Not all trusted canonical rows were retained')
    rows.sort(key=lambda r:(r['observed_at_utc'],r['event_id']))
    select = [r for r in rows if r['event_type']=='iec104_select']
    require(len(select)==1, 'SELECT not unique')
    select_at=ts(select[0]['observed_at_utc'])
    require({r['ioa'] for r in rows if r['event_type']=='iec104_point_read'}=={11,12,13},
            'Incomplete DER point evidence')
    require(all(ts(r['observed_at_utc']) < select_at
                for r in rows if r['event_type'] in ('iec104_interrogation','iec104_point_read')),
            'Pre-select ordering invalid')
    return dict(schema_version='ecpomdg.online_observations.v1', episode_id=run_id,
                observation_count=len(rows), source_event_ids=list(canonical_ids),
                select_event_id=select_event_id, asof_cutoff_utc=cutoff.isoformat(),
                trusted_observation_source='fresh_defender_operational_api',
                trusted_asset_id=REAL, online_ingestion_requested=True,
                observations=rows)


def command(args, *, timeout, interactive=False):
    proc=subprocess.run(args,timeout=timeout,
                        **({} if interactive else {'capture_output':True,'text':True}))
    require(proc.returncode == 0,
            f"SSH/graph step failed ({args[0]}), code={proc.returncode}" +
            ('' if interactive else f' stderr={proc.stderr[-600:]}'))


def commit_and_read_live(run_dir: Path, snapshot: dict) -> dict:
    episode=snapshot['episode_id']
    require(re.fullmatch(r'\d{8}T\d{12}Z',episode), 'Illegal run identifier')
    local=run_dir/'online_predecision_trusted_observations.json'
    require(not local.exists(), 'Do not overwrite evidence snapshot')
    local.write_text(json.dumps(snapshot,sort_keys=True,indent=2)+'\n')
    sha=hashlib.sha256(local.read_bytes()).hexdigest()
    # Existing SSH user configuration supplies host pinning and authentication.
    command(['scp','-o','BatchMode=yes',str(local),
             f'kg:{SERVER_INPUT}/{episode}_online_predecision_trusted_observations.json'],
            timeout=20)
    remote = (
        'EC_POMDG_ONLINE_GRAPH_COMMIT=YES '
        '$HOME/ecpomdg/venvs/neo4j_kg_import/bin/python '
        f'"{SERVER_SCRIPT}" --snapshot '
        f'"$HOME/ecpomdg_setup/dynamic_knowledge_graph/{episode}_online_predecision_trusted_observations.json"'
    )
    print('ONLINE_NEO4J_TRANSACTION_AND_QUERY_BEGIN: BEFORE_DEFENDER_DECISION', flush=True)
    command(['ssh','-tt','-o','ConnectTimeout=10','kg',remote],
            timeout=110,interactive=True)
    local_result=run_dir/'online_predecision_graph_readback.json'
    command(['scp','-o','BatchMode=yes',
             f'kg:{SERVER_OUTPUT}/{episode}_online_graph_ingest_readback.json',
             str(local_result)],timeout=25)
    result=json.loads(local_result.read_text())
    require(result['episode_id']==episode and
            result['snapshot_sha256']==sha and
            result['online_graph_commit_and_query_completed'] is True and
            result['frozen_kg_and_bridge_fingerprint_unchanged'] is True,
            'Remote readback invalid or bound to different episode')
    require(result['event_count']==snapshot['observation_count'] and
            result['select_event_id']==snapshot['select_event_id'] and
            result['snapshot_asof_cutoff_utc']==snapshot['asof_cutoff_utc'],
            'Neo4j observation mismatch')
    its=result['features_by_mask']['I_T']
    require(its['iec104_select_visible'] and
            snapshot['select_event_id'] in its['source_event_ids_asof'] and
            its['validated_topology_ics_bridge_observations']>=1,
            'Required online graph SELECT bridge missing')
    require(result['graph_features_used_for_bayesian_likelihood'] is False and
            result['dynamic_kg_advantage_established'] is False,
            'Graph readback makes unsupported efficacy assertion')
    print('ONLINE_NEO4J_GRAPH_READBACK_BEFORE_POLICY: PASS',flush=True)
    return result


def self_test():
    # No network or Neo4j calls; local source validation only.
    from datetime import timedelta
    base=datetime.now(timezone.utc)
    records=[]
    kinds=['iec104_connection_request','iec104_session_established',
           'iec104_interrogation','iec104_point_read','iec104_point_read',
           'iec104_point_read','iec104_select']
    for i,k in enumerate(kinds):
        obj=dict(event_id=f'ev-{i:03d}', event_type=k, asset_id=REAL,
                 protocol='IEC104',collector_ts_utc=(base+timedelta(milliseconds=i)).isoformat())
        if k=='iec104_point_read':obj['ioa']=[11,12,13][i-3]
        if k=='iec104_select':obj.update(ioa=100,command_phase='select',asdu_type=50,
                                        cause=6,common_address=47,requested=200.0)
        records.append(obj)
    canonical=[records[i]['event_id'] for i in (0,1,2,3,6)]
    valid=create_online_snapshot('20261014T192000000000Z',records,canonical,
                                  canonical[-1],(base+timedelta(seconds=1)).isoformat())
    require(valid['observation_count']==7,'Snapshot count incorrect')
    import copy
    for key,value in [('asset_id','asset-field-002'),('protocol','BAD')]:
        wrong=copy.deepcopy(records);wrong[0][key]=value
        try:create_online_snapshot('20261014T192000000000Z',wrong,canonical,
                                    canonical[-1],(base+timedelta(seconds=1)).isoformat())
        except ValueError: pass
        else:raise AssertionError('Invalid identity accepted')
    future=copy.deepcopy(records)
    future[-1]['collector_ts_utc']=(base+timedelta(seconds=2)).isoformat()
    try:create_online_snapshot('20261014T192000000000Z',future,canonical,
                                canonical[-1],(base+timedelta(seconds=1)).isoformat())
    except ValueError:pass
    else:raise AssertionError('Future event accepted')
    print('PHASE3D2A_TRUSTED_PREDECISION_SNAPSHOT_TESTS: PASS')

if __name__=='__main__':
    self_test()
