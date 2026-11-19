#!/usr/bin/env python3
"""Lossless, resumable import of the three frozen EC-POMDG graphs into Neo4j.

The original JSONL source record is preserved as a canonical JSON string in
kg_record_json; its SHA-256 and each projected scalar property are verified.
All imported graph entities remain under a graph-specific namespace.
"""

import getpass
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from neo4j import GraphDatabase

ROOT = Path.home() / 'ecpomdg'
GRAPH_ROOT = ROOT / 'knowledge_graphs'
OUT = ROOT / 'neo4j_knowledge_graph_migration' / 'results'
BATCH = 400

SOURCES = {
    'general_cyber': ('GeneralCyber', 'general_cyber', 'general_cyber_knowledge_graph', 6171, 31654),
    'power_grid_ics': ('ICSCyber', 'power_grid_ics_cyber', 'power_grid_ics_cyber_knowledge_graph', 467, 1800),
    'component_topology': ('ComponentTopology', 'power_grid_component_topology', 'power_grid_component_topology_knowledge_graph', 104, 176),
}

REL_TYPE = re.compile(r'^[A-Za-z_][A-Za-z_0-9-]*$')
RESERVED = {'kg_uid', 'kg_edge_uid', 'kg_namespace', 'kg_original_id',
            'kg_record_sha256', 'kg_record_json'}


def canonical(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def fingerprint(canonical_json):
    return hashlib.sha256(canonical_json.encode('ascii')).hexdigest()


def project(value):
    """Neo4j property-safe projection; canonical source record stays lossless."""
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Non-finite numeric attribute')
        return value
    if isinstance(value, list):
        # Lists containing nested structures or mixed types become JSON strings.
        if value and all(type(v) is type(value[0]) for v in value) and all(
            isinstance(v, (str, int, float, bool)) for v in value
        ):
            if any(isinstance(v, float) and not math.isfinite(v) for v in value):
                raise ValueError('Non-finite list attribute')
            return value
        return canonical(value)
    if isinstance(value, dict):
        return canonical(value)
    raise TypeError(f'Unsupported source value: {type(value)}')


def projected_props(record):
    if RESERVED.intersection(record):
        raise ValueError('Source record clashes with reserved kg_ metadata')
    return {k: project(v) for k, v in record.items() if v is not None}


def read_jsonl(path):
    with path.open('r', encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f'{path}:{number}: object expected')
                yield record


def load_source(namespace, info):
    label, dirname, prefix, expected_nodes, expected_edges = info
    folder = GRAPH_ROOT / dirname / 'results'
    summary = json.loads((folder / f'{prefix}_summary.json').read_text(encoding='utf-8'))
    nodes = list(read_jsonl(folder / f'{prefix}_nodes.jsonl'))
    edges = list(read_jsonl(folder / f'{prefix}_edges.jsonl'))
    assert len(nodes) == summary['node_count'] == expected_nodes, (namespace, 'nodes')
    assert len(edges) == summary['edge_count'] == expected_edges, (namespace, 'edges')

    node_rows = {}
    for original in nodes:
        original_id = original.get('id')
        if not isinstance(original_id, str) or not original_id:
            raise ValueError(f'{namespace}: invalid node ID')
        uid = namespace + '::' + original_id
        if uid in node_rows:
            raise ValueError(f'{namespace}: duplicate node {uid}')
        payload = canonical(original)
        props = projected_props(original)
        props.update(kg_uid=uid, kg_namespace=namespace, kg_original_id=original_id,
                     kg_record_sha256=fingerprint(payload), kg_record_json=payload)
        node_rows[uid] = props

    edge_rows = []
    edge_types = Counter()
    for ordinal, original in enumerate(edges):
        src, dst, rel = (original.get('source'), original.get('target'), original.get('relation'))
        if not all(isinstance(v, str) and v for v in (src, dst, rel)):
            raise ValueError(f'{namespace}: invalid edge on row {ordinal + 1}')
        if not REL_TYPE.fullmatch(rel):
            raise ValueError(f'{namespace}: unsupported Cypher relationship type {rel!r}')
        a, b = namespace + '::' + src, namespace + '::' + dst
        if a not in node_rows or b not in node_rows:
            raise ValueError(f'{namespace}: dangling edge {src} -> {dst}')
        payload = canonical(original)
        edge_uid = f'{namespace}::{ordinal:08d}'
        props = projected_props(original)
        props.update(kg_edge_uid=edge_uid, kg_namespace=namespace,
                     kg_record_sha256=fingerprint(payload), kg_record_json=payload)
        edge_rows.append({'a': a, 'b': b, 'typ': rel, 'uid': edge_uid, 'props': props})
        edge_types[rel] += 1

    return {
        'label': label, 'nodes': node_rows, 'edges': edge_rows,
        'edge_types': edge_types, 'node_count': expected_nodes,
        'edge_count': expected_edges,
    }


def chunks(items, size=BATCH):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def write_batch(tx, query, rows):
    tx.run(query, rows=rows).consume()


def import_graph(driver, namespace, graph):
    label = graph['label']  # fixed, source-independent allowlist
    node_query = (
        'UNWIND $rows AS row '
        f'MERGE (n:KGNode:{label} {{kg_uid: row.kg_uid}}) '
        'SET n += row'
    )
    with driver.session(database='neo4j') as session:
        rows = list(graph['nodes'].values())
        for ix, batch in enumerate(chunks(rows), 1):
            session.execute_write(write_batch, node_query, batch)
        print(f'{namespace} NODE_IMPORT: {len(rows)}', flush=True)

        grouped = defaultdict(list)
        for row in graph['edges']:
            grouped[row['typ']].append(row)
        for rel in sorted(grouped):
            # Backtick-quote the original type, retaining e.g. "attributed-to".
            # Syntax is safe because we validated REL_TYPE above.
            query = (
                'UNWIND $rows AS row '
                'MATCH (a:KGNode {kg_uid: row.a}) '
                'MATCH (b:KGNode {kg_uid: row.b}) '
                f'MERGE (a)-[r:`{rel}` {{kg_edge_uid: row.uid}}]->(b) '
                'SET r += row.props'
            )
            for batch in chunks(grouped[rel]):
                session.execute_write(write_batch, query, batch)
        print(f'{namespace} RELATIONSHIP_IMPORT: {len(graph["edges"])}', flush=True)


def verify_graph(driver, namespace, graph):
    expected_nodes = graph['nodes']
    expected_edges = {row['uid']: row for row in graph['edges']}
    seen_nodes = set()
    seen_edges = set()
    counts = Counter()

    with driver.session(database='neo4j', fetch_size=500) as session:
        for rec in session.run(
            'MATCH (n:KGNode {kg_namespace: $namespace}) RETURN labels(n) AS labels, properties(n) AS p',
            namespace=namespace,
        ):
            props = rec['p']
            uid = props['kg_uid']
            assert uid in expected_nodes and uid not in seen_nodes, ('unexpected/duplicate node', uid)
            assert graph['label'] in rec['labels'], ('missing label', uid)
            expected = expected_nodes[uid]
            assert props == expected, ('node property mismatch', uid, props, expected)
            assert fingerprint(props['kg_record_json']) == props['kg_record_sha256'], ('node hash', uid)
            seen_nodes.add(uid)
        assert len(seen_nodes) == len(expected_nodes), ('node count mismatch', namespace, len(seen_nodes))
        print(f'{namespace} NODE_RECORD_FIDELITY: PASS', flush=True)

        for rec in session.run(
            'MATCH (a:KGNode {kg_namespace: $namespace})-[r]->(b:KGNode) '
            'RETURN a.kg_uid AS a, b.kg_uid AS b, type(r) AS typ, properties(r) AS p',
            namespace=namespace,
        ):
            props = rec['p']
            uid = props.get('kg_edge_uid')
            assert uid in expected_edges and uid not in seen_edges, ('unexpected/duplicate edge', uid)
            expected = expected_edges[uid]
            assert rec['a'] == expected['a'] and rec['b'] == expected['b'], ('endpoint mismatch', uid)
            assert rec['typ'] == expected['typ'], ('relationship type mismatch', uid)
            assert props == expected['props'], ('edge property mismatch', uid)
            assert fingerprint(props['kg_record_json']) == props['kg_record_sha256'], ('edge hash', uid)
            assert props['kg_namespace'] == namespace
            seen_edges.add(uid)
            counts[rec['typ']] += 1
        assert len(seen_edges) == len(expected_edges), ('edge count mismatch', namespace, len(seen_edges))
        assert counts == graph['edge_types'], ('relationship multiplicity mismatch', namespace)
        print(f'{namespace} RELATIONSHIP_RECORD_FIDELITY: PASS', flush=True)

    return {
        'namespace': namespace,
        'nodes': len(seen_nodes),
        'relationships': len(seen_edges),
        'relationship_types': dict(sorted(counts.items())),
        'status': 'PASS',
    }


def main():
    print('===== VALIDATE ALL FROZEN JSONL SOURCES BEFORE WRITING =====', flush=True)
    graphs = {namespace: load_source(namespace, info) for namespace, info in SOURCES.items()}
    for namespace, graph in graphs.items():
        print(f'{namespace} SOURCE_RECORDS: {graph["node_count"]} nodes / {graph["edge_count"]} edges - PASS', flush=True)

    password = getpass.getpass('Existing Neo4j administrator password: ')
    try:
        with GraphDatabase.driver('bolt://127.0.0.1:7687', auth=('neo4j', password)) as driver:
            driver.verify_connectivity()
            print('NEO4J_AUTHENTICATED_DRIVER: PASS', flush=True)
            with driver.session(database='neo4j') as session:
                total = session.run('MATCH (n) RETURN count(n) AS c').single()['c']
                existing = session.run('MATCH (n:KGNode) RETURN count(n) AS c').single()['c']
                if total != existing:
                    raise SystemExit('SAFE_IMPORT_STOP: Neo4j contains unrelated nodes')
                unknown = session.run(
                    'MATCH (n:KGNode) WHERE NOT n.kg_namespace IN $names '
                    'RETURN count(n) AS c', names=list(SOURCES)
                ).single()['c']
                if unknown:
                    raise SystemExit('SAFE_IMPORT_STOP: Unknown KG namespaces already exist')
                # Do not allow this importer to affect other relationship datasets.
                existing_rels = session.run('MATCH ()-[r]->() RETURN count(r) AS c').single()['c']
                tagged_rels = session.run(
                    'MATCH ()-[r]->() WHERE r.kg_namespace IN $names RETURN count(r) AS c',
                    names=list(SOURCES)
                ).single()['c']
                if existing_rels != tagged_rels:
                    raise SystemExit('SAFE_IMPORT_STOP: Untagged/foreign relationships exist')
                session.run(
                    'CREATE CONSTRAINT ec_pomdg_kg_uid_unique IF NOT EXISTS '
                    'FOR (n:KGNode) REQUIRE n.kg_uid IS UNIQUE'
                ).consume()
            print('KG_NODE_UNIQUENESS_CONSTRAINT: PASS', flush=True)

            for namespace, graph in graphs.items():
                import_graph(driver, namespace, graph)

            print('===== INDEPENDENT FULL-RECORD NEO4J VALIDATION =====', flush=True)
            validations = [verify_graph(driver, namespace, graph)
                           for namespace, graph in graphs.items()]
            with driver.session(database='neo4j') as session:
                total_nodes = session.run('MATCH (n) RETURN count(n) AS c').single()['c']
                total_edges = session.run('MATCH ()-[r]->() RETURN count(r) AS c').single()['c']
            assert total_nodes == 6742, total_nodes
            assert total_edges == 33630, total_edges
            print('NEO4J_TOTAL_NODES: 6742 - PASS', flush=True)
            print('NEO4J_TOTAL_RELATIONSHIPS: 33630 - PASS', flush=True)
    finally:
        password = None

    summary = {
        'built_utc': datetime.now(timezone.utc).isoformat(),
        'database': 'neo4j',
        'server': 'neo4j-community-2026.09.0',
        'driver_major': 6,
        'source_graphs': validations,
        'total_nodes': 6742,
        'total_relationships': 33630,
        'record_fidelity': 'all node and edge fields; exact endpoint and relationship-type comparison',
        'status': 'PASS',
    }
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / 'neo4j_three_kg_migration_validation_summary.json'
    dest.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='ascii')
    print('VALIDATION_SUMMARY:', dest, flush=True)
    print('NEO4J_THREE_FROZEN_KGS_MIGRATION: PASS', flush=True)


if __name__ == '__main__':
    main()
