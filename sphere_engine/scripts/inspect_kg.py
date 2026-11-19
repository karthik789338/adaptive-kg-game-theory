#!/usr/bin/env python3
"""Read-only inspector for the EC-POMDG Neo4j graphs.

Prints the schema and samples of your three knowledge graphs (loaded under the
:KGNode label with kg_namespace in {general_cyber, power_grid_ics,
component_topology}) and the campaign-memory layer (:Actor / :CampaignObservation).
It only runs MATCH/RETURN queries -- it never creates, updates, or deletes
anything.

Usage:
    export NEO4J_URI=bolt://127.0.0.1:7687     # tunnel end, or bolt://10.50.0.30:7687
    export NEO4J_PASSWORD=...                   # your neo4j password
    python3 scripts/inspect_kg.py
    # options: --uri --user --password --database --samples N
"""
from __future__ import annotations
import argparse
import os
from collections import Counter

from neo4j import GraphDatabase


def q(session, cypher, **params):
    return list(session.run(cypher, **params))


def hr(title):
    print("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"))
    ap.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    ap.add_argument("--samples", type=int, default=5, help="sample rows per section")
    args = ap.parse_args()
    if not args.password:
        raise SystemExit("Set NEO4J_PASSWORD (env) or pass --password")

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password), connection_timeout=10)
    with driver.session(database=args.database) as s:

        hr("OVERVIEW")
        total = q(s, "MATCH (n) RETURN count(n) AS n")[0]["n"]
        kg = q(s, "MATCH (n:KGNode) RETURN count(n) AS n")[0]["n"]
        rels = q(s, "MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
        print(f"total nodes: {total}   :KGNode nodes: {kg}   total relationships: {rels}")

        hr("NODE LABELS (all)")
        for row in q(s, "MATCH (n) UNWIND labels(n) AS l RETURN l AS label, count(*) AS c ORDER BY c DESC"):
            print(f"  {row['label']:<28} {row['c']}")

        hr("RELATIONSHIP TYPES (all)")
        for row in q(s, "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC"):
            print(f"  {row['t']:<34} {row['c']}")

        hr("KGNode BY NAMESPACE (your 3 KGs)")
        ns_rows = q(s, "MATCH (n:KGNode) RETURN coalesce(n.kg_namespace,'<none>') AS ns, count(*) AS c ORDER BY c DESC")
        for row in ns_rows:
            print(f"  {row['ns']:<22} {row['c']}")
        namespaces = [r["ns"] for r in ns_rows if r["ns"] != "<none>"]

        hr("KGNode PROPERTY KEYS (sampled)")
        keys = Counter()
        for row in q(s, "MATCH (n:KGNode) WITH n LIMIT 2000 UNWIND keys(n) AS k RETURN k", ):
            keys[row["k"]] += 1
        for k, c in keys.most_common():
            print(f"  {k:<28} seen on {c} of up to 2000 sampled nodes")

        for ns in namespaces:
            hr(f"NAMESPACE: {ns}")
            # secondary labels besides KGNode
            lab = q(s, "MATCH (n:KGNode {kg_namespace:$ns}) UNWIND labels(n) AS l "
                       "WITH l WHERE l<>'KGNode' RETURN l AS label, count(*) AS c ORDER BY c DESC", ns=ns)
            if lab:
                print("  secondary node labels:")
                for r in lab:
                    print(f"    {r['label']:<26} {r['c']}")
            # node_type property breakdown if present
            nt = q(s, "MATCH (n:KGNode {kg_namespace:$ns}) WHERE n.node_type IS NOT NULL "
                      "RETURN n.node_type AS t, count(*) AS c ORDER BY c DESC LIMIT 25", ns=ns)
            if nt:
                print("  node_type values:")
                for r in nt:
                    print(f"    {str(r['t']):<26} {r['c']}")
            # relationship types originating in this namespace
            rt = q(s, "MATCH (a:KGNode {kg_namespace:$ns})-[r]->(b) "
                      "RETURN type(r) AS t, count(*) AS c ORDER BY c DESC LIMIT 25", ns=ns)
            if rt:
                print("  outgoing relationship types:")
                for r in rt:
                    print(f"    {r['t']:<30} {r['c']}")
            # sample nodes
            print(f"  sample nodes (up to {args.samples}):")
            for r in q(s, "MATCH (n:KGNode {kg_namespace:$ns}) RETURN n.kg_uid AS uid, "
                          "[l IN labels(n) WHERE l<>'KGNode'] AS labels, "
                          "coalesce(n.name, n.title, n.id, '') AS name LIMIT $k", ns=ns, k=args.samples):
                print(f"    {r['uid']}  {r['labels']}  {r['name']}")
            # sample edges
            print(f"  sample edges (up to {args.samples}):")
            for r in q(s, "MATCH (a:KGNode {kg_namespace:$ns})-[r]->(b:KGNode) "
                          "RETURN a.kg_uid AS a, type(r) AS rel, b.kg_uid AS b, "
                          "coalesce(b.kg_namespace,'?') AS b_ns LIMIT $k", ns=ns, k=args.samples):
                print(f"    ({r['a']}) -[{r['rel']}]-> ({r['b']}) [{r['b_ns']}]")

        hr("CROSS-NAMESPACE EDGES (semantic bridges between the 3 KGs)")
        xr = q(s, "MATCH (a:KGNode)-[r]->(b:KGNode) WHERE a.kg_namespace <> b.kg_namespace "
                  "RETURN a.kg_namespace AS src, type(r) AS rel, b.kg_namespace AS dst, count(*) AS c "
                  "ORDER BY c DESC LIMIT 25")
        if xr:
            for r in xr:
                print(f"  {r['src']} -[{r['rel']}]-> {r['dst']}   {r['c']}")
        else:
            print("  (none found)")

        hr("CAMPAIGN MEMORY LAYER (added by ecpomdg dynamic KG)")
        for lbl in ("Actor", "CampaignObservation", "Episode", "RuntimeObservation", "EventSemantic", "AttackStage"):
            c = q(s, f"MATCH (n:{lbl}) RETURN count(n) AS n")[0]["n"]
            print(f"  :{lbl:<22} {c}")
        pops = q(s, "MATCH (n:CampaignObservation) WHERE n.population IS NOT NULL "
                    "RETURN n.population AS pop, count(*) AS c ORDER BY c DESC")
        for r in pops:
            print(f"    population '{r['pop']}': {r['c']} campaign observations")

    driver.close()
    print("\n(read-only inspection complete; nothing was modified)")


if __name__ == "__main__":
    main()
