#!/usr/bin/env python3
"""Read-only visualizations for the three frozen EC-POMDG knowledge graphs.

Builds small interpretable PyVis HTML views rather than rendering 33,630
relationships at once. Never modifies source graph files.
"""
import argparse
import hashlib
import html
import json
import math
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from pyvis.network import Network

SPECS = {
    "general_cyber": {
        "folder": "general_cyber",
        "prefix": "general_cyber_knowledge_graph",
        "expected": (6171, 31654),
    },
    "power_grid_ics": {
        "folder": "power_grid_ics_cyber",
        "prefix": "power_grid_ics_cyber_knowledge_graph",
        "expected": (467, 1800),
    },
    "component_topology": {
        "folder": "power_grid_component_topology",
        "prefix": "power_grid_component_topology_knowledge_graph",
        "expected": (104, 176),
    },
}

PALETTE = {
    "attack": "#60a5fa", "ics": "#a78bfa", "capec": "#c084fc",
    "cwe": "#fbbf24", "cve": "#fb7185", "vendor": "#2dd4bf",
    "product": "#34d399", "network": "#38bdf8", "cyber_asset": "#60a5fa",
    "application_service": "#e879f9", "grid": "#34d399",
    "trusted": "#fbbf24", "experiment": "#f97316",
    "default": "#94a3b8",
}


def read_jsonl(path):
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def sha256(path):
    d = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            d.update(chunk)
    return d.hexdigest()


def load_graph(root, spec):
    results = root / spec["folder"] / "results"
    prefix = spec["prefix"]
    nfile = results / (prefix + "_nodes.jsonl")
    efile = results / (prefix + "_edges.jsonl")
    sfile = results / (prefix + "_summary.json")
    nodes = read_jsonl(nfile)
    edges = read_jsonl(efile)
    summary = json.loads(sfile.read_text(encoding="utf-8"))
    ids = {row["id"] for row in nodes}
    assert len(ids) == len(nodes), f"duplicate node id: {prefix}"
    assert all(e["source"] in ids and e["target"] in ids for e in edges), f"dangling edge: {prefix}"
    actual = (len(nodes), len(edges))
    assert actual[0] >= spec["expected"][0] and actual[1] >= spec["expected"][1], f"{prefix}: counts below expected {actual} < {spec['expected']}"
    assert actual == (summary["node_count"], summary["edge_count"]), f"summary mismatch: {prefix}"
    indexed = {row["id"]: row for row in nodes}
    adj = defaultdict(set)
    for e in edges:
        adj[e["source"]].add(e["target"])
        adj[e["target"]].add(e["source"])
    return {
        "nodes": indexed, "edges": edges, "adj": adj, "summary": summary,
        "sources": {p.name: sha256(p) for p in (nfile, efile, sfile)},
    }


def kind_color(kind):
    if kind.startswith("attack_"): return PALETTE["attack"]
    if kind.startswith("ics_"): return PALETTE["ics"]
    if kind.startswith("capec_"): return PALETTE["capec"]
    if kind.startswith("cwe_"): return PALETTE["cwe"]
    if kind == "cve": return PALETTE["cve"]
    if kind in ("vendor", "product"): return PALETTE[kind]
    if kind == "network_segment" or kind == "network_interface": return PALETTE["network"]
    if kind == "cyber_asset": return PALETTE["cyber_asset"]
    if kind == "application_service": return PALETTE["application_service"]
    if kind.startswith("power_grid"): return PALETTE["grid"]
    if kind == "trusted_asset_identity": return PALETTE["trusted"]
    if kind.startswith("experiment_") or kind.startswith("iec104_"): return PALETTE["experiment"]
    return PALETTE["default"]


def make_network(cdn, n):
    net = Network(
        height="770px", width="100%", directed=True,
        bgcolor="#0b1220", font_color="#f8fafc",
        notebook=False, select_menu=False, filter_menu=False,
        cdn_resources=cdn,
    )
    # Limit force work; stable performance on modest SPHERE VMs.
    net.set_options(json.dumps({
        "physics": {
            "enabled": n <= 130,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
                "gravitationalConstant": -60,
                "centralGravity": 0.01,
                "springLength": 130,
                "springConstant": 0.045,
            },
            "stabilization": {"enabled": True, "iterations": 100},
        },
        "interaction": {
            "hover": True, "navigationButtons": True,
            "keyboard": True, "multiselect": True,
        },
        "nodes": {"font": {"size": 14}},
        "edges": {"smooth": {"type": "dynamic"}},
    }))
    return net


def label(row):
    kind = row.get("node_type", "")
    if kind == "network_interface":
        return str(row.get("ip_address", row["id"]))[:38]
    if kind == "cyber_asset":
        return str(row.get("hostname", row["id"]))[:38]
    if kind == "power_grid_bus":
        return "BUS " + str(row.get("name", ""))
    return str(row.get("external_id") or row.get("name") or row["id"])[:37]


def tooltip(row):
    keep = ("name", "external_id", "node_type", "source_dataset", "role",
            "component_class", "trusted_asset_id", "ip_address", "endpoint",
            "physical_grid_connected", "description")
    return "".join(
        f"<b>{html.escape(k)}</b>: {html.escape(str(row[k])[:260])}<br>"
        for k in keep if k in row and row[k] not in (None, "")
    )


def make_selection(graph, anchors, hops=1, cap=90, priority=None):
    nodes, adj = graph["nodes"], graph["adj"]
    anchors = list(anchors)
    assert all(a in nodes for a in anchors), f"missing anchor(s): {[a for a in anchors if a not in nodes]}"
    seen = set(anchors)
    queue = deque((a, 0) for a in anchors)
    while queue and len(seen) < cap:
        node_id, depth = queue.popleft()
        if depth == hops:
            continue
        candidates = sorted(adj[node_id], key=lambda candidate: (
            (priority or {}).get(nodes[candidate].get("node_type", ""), 9),
            candidate,
        ))
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            queue.append((candidate, depth + 1))
            if len(seen) >= cap:
                break
    return seen


def render_subgraph(graph, selected, filename, out, cdn, title, anchors=(), edge_cap=350):
    nodes = graph["nodes"]
    selected = set(selected)
    assert selected and selected.issubset(nodes)
    assert len(selected) <= 160, f"view too large: {filename}"
    net = make_network(cdn, len(selected))
    anchor_set = set(anchors)
    for node_id in sorted(selected):
        record = nodes[node_id]
        kind = record.get("node_type", "unknown")
        net.add_node(
            node_id, label=label(record), title=tooltip(record),
            color=kind_color(kind), size=31 if node_id in anchor_set else 17,
            shape="dot", group=kind,
        )
    eligible = [e for e in graph["edges"] if e["source"] in selected and e["target"] in selected]
    eligible.sort(key=lambda e: (
        0 if (e["source"] in anchor_set or e["target"] in anchor_set) else 1,
        e["source"], e["target"], e.get("relation", ""), str(e.get("edge_key", "")),
    ))
    eligible = eligible[:edge_cap]
    for edge in eligible:
        rel = str(edge.get("relation", "related_to"))
        net.add_edge(edge["source"], edge["target"],
                     title=html.escape(rel), color="#64748b", width=1.4, arrows="to")
    path = out / filename
    net.write_html(str(path))
    validate_html(path)
    print(f"{filename}: {len(selected)} nodes, {len(eligible)} edges")
    return {"title": title, "file": filename, "nodes": len(selected),
            "edges": len(eligible), "source_edge_count_not_clipped": sum(
                1 for e in graph["edges"] if e["source"] in selected and e["target"] in selected),
            "sha256": sha256(path)}


def render_type_overview(graph, filename, out, cdn, title):
    nodes, edges = graph["nodes"], graph["edges"]
    counts = Counter(row.get("node_type", "unknown") for row in nodes.values())
    pair_counts = Counter((nodes[e["source"]].get("node_type", "unknown"),
                           nodes[e["target"]].get("node_type", "unknown")) for e in edges)
    net = make_network(cdn, len(counts))
    for kind, count in sorted(counts.items()):
        net.add_node(kind, label=f"{kind}\n({count:,})",
                     title=f"{html.escape(kind)}: {count:,} source nodes",
                     color=kind_color(kind), size=min(55, 14 + math.log1p(count) * 6))
    for (src, dst), n in sorted(pair_counts.items()):
        net.add_edge(src, dst, title=f"{n:,} typed relationships",
                     color="#64748b", width=min(10, 1 + math.log1p(n)), arrows="to")
    path = out / filename
    net.write_html(str(path))
    validate_html(path)
    print(f"{filename}: {len(counts)} types, {len(pair_counts)} type-pairs")
    return {"title": title, "file": filename,
            "nodes": len(counts), "edges": len(pair_counts),
            "note": "Aggregated categories, not the complete node graph",
            "sha256": sha256(path)}


def validate_html(path):
    content = path.read_text(encoding="utf-8")
    assert path.stat().st_size > 2000, f"HTML suspiciously small: {path}"
    assert "vis-network" in content or "vis.Network" in content, f"No visualization library: {path}"
    assert "network" in content.lower() and "nodes" in content.lower(), f"No graph data: {path}"


def find_ext(graph, eid):
    matches = [id_ for id_, row in graph["nodes"].items() if row.get("external_id") == eid]
    assert len(matches) == 1, f"external id {eid} missing or ambiguous: {matches}"
    return matches[0]


def make_index(report, output_dir):
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>EC-POMDG Knowledge Graph Visualizations</title>',
        '<style>body{font-family:system-ui,sans-serif;background:#0b1220;color:#e5e7eb;',
        'max-width:960px;margin:40px auto;padding:0 20px}a{color:#93c5fd}',
        '.card{background:#172033;border:1px solid #334155;border-radius:12px;',
        'padding:18px;margin:14px 0}.muted{color:#94a3b8;font-size:14px}</style>',
        '</head><body><h1>EC-POMDG Knowledge Graph Visualizations</h1>',
        '<p>Source: three validated, frozen JSONL graphs. This is a visualization ',
        'package; source files were not modified. Zoom, drag, hover and inspect edges.</p>',
    ]
    for name, view_group in report["views"].items():
        parts.append(f'<h2>{html.escape(name.replace("_", " ").title())}</h2>')
        for view in view_group:
            parts.append('<div class="card">')
            parts.append(f'<a href="{html.escape(view["file"], quote=True)}">'
                         f'{html.escape(view["title"])}</a>')
            parts.append(f'<div class="muted">{view["nodes"]} displayed nodes / '
                         f'{view["edges"]} displayed edges</div>')
            if "note" in view:
                parts.append(f'<div class="muted">{html.escape(view["note"])}</div>')
            parts.append('</div>')
    parts.append('<p class="muted">If a graph appears blank, the browser may be blocking the '
                 'remote visualization CDN. Rebuild with ECPOMDG_PYVIS_CDN=in_line.</p>')
    parts.append('</body></html>')
    path = output_dir / "index.html"
    path.write_text("".join(parts), encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kg-root", type=Path, default=Path.home() / "ecpomdg" / "knowledge_graphs")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--cdn", choices=("remote", "in_line"), default="remote")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    graphs = {name: load_graph(args.kg_root, spec) for name, spec in SPECS.items()}
    views = defaultdict(list)

    def add(group, entry):
        views[group].append(entry)

    g = graphs["general_cyber"]
    add("general_cyber", render_type_overview(
        g, "general_cyber_type_overview.html", args.output, args.cdn, "General cyber — node and relationship types"))
    t1059 = find_ext(g, "T1059")
    add("general_cyber", render_subgraph(
        g, make_selection(g, [t1059], 1, 100, {"attack_malware": 0, "attack_intrusion_set": 1, "attack_tool": 2}),
        "general_cyber_attack_t1059_neighborhood.html", args.output, args.cdn,
        "General cyber — ATT&CK T1059 neighborhood", [t1059], 240))
    cve = "CVE::CVE-2021-44228"
    assert cve in g["nodes"]
    selected = make_selection(g, [cve], 1, 24)
    for node_id in sorted(list(selected)):
        if g["nodes"][node_id].get("node_type") in ("cwe_weakness", "product"):
            selected |= make_selection(g, [node_id], 1, 30)
        if len(selected) > 108:
            selected = set(sorted(selected)[:108]) | {cve}
    add("general_cyber", render_subgraph(
        g, selected, "general_cyber_cve_cwe_capec_neighborhood.html", args.output,
        args.cdn, "General cyber — CVE/CWE/CAPEC vulnerability neighborhood", [cve], 250))

    g = graphs["power_grid_ics"]
    add("power_grid_ics", render_type_overview(
        g, "power_grid_ics_type_overview.html", args.output, args.cdn, "ICS — node and relationship types"))
    for soft, title in (("S0604", "Industroyer"), ("S1072", "Industroyer2")):
        anchor = find_ext(g, soft)
        add("power_grid_ics", render_subgraph(
            g, make_selection(g, [anchor], 1, 105),
            f"power_grid_ics_{title.lower()}_neighborhood.html", args.output, args.cdn,
            f"ICS — {title} native ATT&CK neighborhood", [anchor], 320))
    scenario = "EXPERIMENT::ecpomdg-industroyer-inspired-iec104"
    assert scenario in g["nodes"]
    selected = make_selection(g, [scenario], 2, 110, {
        "experiment_behavior": 0, "industrial_protocol": 1, "iec104_control_point": 1,
        "ics_attack_pattern": 2, "experiment_evidence": 3,
    })
    add("power_grid_ics", render_subgraph(
        g, selected, "power_grid_ics_iec104_experiment_neighborhood.html",
        args.output, args.cdn, "ICS — IEC-104 experiment and technique mappings", [scenario], 320))

    g = graphs["component_topology"]
    add("component_topology", render_type_overview(
        g, "component_topology_type_overview.html", args.output, args.cdn,
        "Component and topology — node and relationship types"))
    cyber_nodes = {id_ for id_, row in g["nodes"].items()
                   if row.get("node_type") in ("cyber_asset", "application_service", "network_interface",
                                                     "network_segment", "trusted_asset_identity")}
    add("component_topology", render_subgraph(
        g, cyber_nodes, "component_topology_sphere_network.html", args.output, args.cdn,
        "Topology — all SPHERE assets, interfaces, networks and services", ["ASSET::controller", "ASSET::decoy"], 220))
    grid_nodes = {id_ for id_, row in g["nodes"].items()
                  if row.get("node_type") in ("power_grid_bus", "power_grid_component", "power_grid_system")}
    add("component_topology", render_subgraph(
        g, grid_nodes, "component_topology_ieee13_physical_grid.html", args.output, args.cdn,
        "Topology — all OpenDSS grid components, IEEE-13 buses and smart inverter",
        ["GRID_ELEMENT::pvsystem.ecpomdg_der", "GRID_BUS::675"], 240))
    add("component_topology", render_subgraph(
        g, set(g["nodes"]), "component_topology_complete_104_node_graph.html", args.output,
        args.cdn, "Topology — complete validated 104-node cyber-physical graph",
        ["ASSET::controller", "ASSET::decoy", "GRID_ELEMENT::pvsystem.ecpomdg_der"], 240))
    bridge = {"ASSET::scada", "ASSET::controller", "ASSET::decoy", "ASSET::gridsim",
              "ASSET::collector", "ASSET::defender", "GRID_SYSTEM::ieee13",
              "GRID_ELEMENT::pvsystem.ecpomdg_der", "GRID_BUS::675"}
    assert bridge.issubset(g["nodes"])
    add("component_topology", render_subgraph(
        g, bridge, "component_topology_real_decoy_physical_control_bridge.html", args.output,
        args.cdn, "Topology — real vs decoy physical-control bridge",
        ["ASSET::controller", "ASSET::decoy", "GRID_ELEMENT::pvsystem.ecpomdg_der"], 80))

    report = {
        "status": "validated_visualizations_built_from_frozen_graphs",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "cdn_resources": args.cdn,
        "source_graphs": {
            name: {"node_count": len(g["nodes"]), "edge_count": len(g["edges"]), "source_sha256": g["sources"]}
            for name, g in graphs.items()
        },
        "views": dict(views),
    }
    make_index(report, args.output)
    report_path = args.output / "knowledge_graph_visualization_manifest.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Validate every visualization is present and well formed.
    for group in report["views"].values():
        for view in group:
            path = args.output / view["file"]
            validate_html(path)
            assert sha256(path) == view["sha256"]
    print(f"VALIDATED_VISUALIZATION_COUNT: {sum(len(v) for v in views.values())}")
    print("ALL_THREE_KG_VISUALIZATIONS: PASS")


if __name__ == "__main__":
    main()
