#!/usr/bin/env python3

import ipaddress
import json
from collections import Counter
from pathlib import Path

import networkx as nx


BASE = (
    Path.home()
    / "ecpomdg"
    / "knowledge_graphs"
    / "power_grid_component_topology"
)

SOURCE = BASE / "source"
RESULTS = BASE / "results"


TOPOLOGY = json.loads(
    (
        SOURCE
        / "sphere_cyber_physical_topology_manifest.json"
    ).read_text(
        encoding="utf-8"
    )
)

LIVE = json.loads(
    (
        SOURCE
        / "sphere_live_interface_validation.json"
    ).read_text(
        encoding="utf-8"
    )
)

PHYSICAL = json.loads(
    (
        SOURCE
        / "ieee13_physical_topology_snapshot.json"
    ).read_text(
        encoding="ascii"
    )
)

REGISTRY = json.loads(
    (
        SOURCE
        / "defender_trusted_asset_registry.json"
    ).read_text(
        encoding="utf-8"
    )
)


graph = nx.MultiDiGraph(
    name=(
        "EC-POMDG Power-Grid "
        "Component + Topology Knowledge Graph"
    )
)


def scalar(value):

    if value is None:
        return ""

    if isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
    )


def add_node(
    node,
    **attrs,
):

    graph.add_node(
        node,
        **{
            key:
                scalar(value)
            for key, value
            in attrs.items()
        },
    )


def add_edge(
    source,
    target,
    relation,
    **attrs,
):

    assert graph.has_node(
        source
    ), source

    assert graph.has_node(
        target
    ), target

    graph.add_edge(
        source,
        target,
        relation=
            relation,
        **{
            key:
                scalar(value)
            for key, value
            in attrs.items()
        },
    )


# ================================================================
# CYBER NETWORK SEGMENTS
# ================================================================

print(
    "===== CYBER TOPOLOGY ====="
)


network_lookup = {}


for name, cidr in (
    TOPOLOGY[
        "network_segments"
    ].items()
):

    node = (
        "NETWORK::"
        + name
    )

    network_lookup[
        name
    ] = node

    add_node(
        node,
        node_type=
            "network_segment",
        name=
            name,
        cidr=
            cidr,
        source_dataset=
            "SPHERE topology manifest",
    )


# ================================================================
# CYBER ASSETS + INTERFACES
# ================================================================

asset_lookup = {}


for asset, config in (
    TOPOLOGY[
        "assets"
    ].items()
):

    node = (
        "ASSET::"
        + asset
    )

    asset_lookup[
        asset
    ] = node

    add_node(
        node,
        node_type=
            "cyber_asset",
        hostname=
            asset,
        role=
            config[
                "role"
            ],
        trusted_asset_id=
            config.get(
                "trusted_asset_id",
                "",
            ),
        physical_grid_connected=
            config.get(
                "physical_grid_connected",
                "",
            ),
        live_interface_validation=
            LIVE[
                "assets"
            ][
                asset
            ][
                "ok"
            ],
        source_dataset=
            "SPHERE topology manifest",
    )


    for ip in config[
        "interfaces"
    ]:

        interface = (
            "INTERFACE::"
            + asset
            + "::"
            + ip
        )

        add_node(
            interface,
            node_type=
                "network_interface",
            ip_address=
                ip,
            source_dataset=
                "SPHERE live interface validation",
        )

        add_edge(
            node,
            interface,
            relation=
                "has_interface",
        )


        address = ipaddress.ip_address(
            ip
        )

        matched = False

        for network_name, cidr in (
            TOPOLOGY[
                "network_segments"
            ].items()
        ):

            if address in ipaddress.ip_network(
                cidr
            ):

                add_edge(
                    interface,
                    network_lookup[
                        network_name
                    ],
                    relation=
                        "attached_to_network",
                )

                matched = True

                break

        assert matched, (
            asset,
            ip,
        )


# ================================================================
# APPLICATION SERVICES
# ================================================================

service_lookup = {}


for service in TOPOLOGY[
    "services"
]:

    node = (
        "SERVICE::"
        + service[
            "id"
        ]
    )

    service_lookup[
        service[
            "id"
        ]
    ] = node

    add_node(
        node,
        node_type=
            "application_service",
        name=
            service[
                "id"
            ],
        protocol=
            service[
                "protocol"
            ],
        endpoint=
            service[
                "endpoint"
            ],
        source_dataset=
            "SPHERE topology manifest",
    )

    add_edge(
        asset_lookup[
            service[
                "asset"
            ]
        ],
        node,
        relation=
            "hosts_service",
    )


# ================================================================
# CYBER RELATIONSHIPS
# ================================================================

for relation in TOPOLOGY[
    "relationships"
]:

    add_edge(
        asset_lookup[
            relation[
                "source"
            ]
        ],
        asset_lookup[
            relation[
                "target"
            ]
        ],
        relation=
            relation[
                "relation"
            ],
        protocol=
            relation.get(
                "protocol",
                "",
            ),
        source_dataset=
            "SPHERE experiment design",
    )


# ================================================================
# DEFENDER TRUSTED ASSET REGISTRY
# ================================================================

print(
    "===== TRUSTED DEFENDER ASSET IDENTITIES ====="
)


for trusted_id, entry in (
    REGISTRY[
        "assets"
    ].items()
):

    hostname = entry[
        "hostname"
    ]

    if hostname not in asset_lookup:
        continue

    trusted_node = (
        "TRUSTED_ASSET::"
        + trusted_id
    )

    add_node(
        trusted_node,
        node_type=
            "trusted_asset_identity",
        trusted_asset_id=
            trusted_id,
        asset_role=
            entry[
                "asset_role"
            ],
        physical_grid_connected=
            entry[
                "physical_grid_connected"
            ],
        source_dataset=
            "Defender trusted asset registry",
    )

    add_edge(
        asset_lookup[
            hostname
        ],
        trusted_node,
        relation=
            "identified_by",
    )


# ================================================================
# PHYSICAL GRID ROOT
# ================================================================

print(
    "===== PHYSICAL POWER-GRID TOPOLOGY ====="
)


grid_root = (
    "GRID_SYSTEM::ieee13"
)

add_node(
    grid_root,
    node_type=
        "power_grid_system",
    name=
        "IEEE 13 Node Test Feeder",
    converged=
        PHYSICAL[
            "converged"
        ],
    source_dataset=
        "OpenDSS physical topology snapshot",
)


# ================================================================
# GRID BUSES
# ================================================================

bus_lookup = {}


for bus in PHYSICAL[
    "buses"
]:

    node = (
        "GRID_BUS::"
        + bus
    )

    bus_lookup[
        bus
    ] = node

    add_node(
        node,
        node_type=
            "power_grid_bus",
        name=
            bus,
        source_dataset=
            "OpenDSS physical topology snapshot",
    )

    add_edge(
        grid_root,
        node,
        relation=
            "contains_bus",
    )


# ================================================================
# GRID COMPONENTS
# ================================================================

element_lookup = {}


for element in PHYSICAL[
    "elements"
]:

    node = (
        "GRID_ELEMENT::"
        + element[
            "full_name"
        ].lower()
    )

    element_lookup[
        element[
            "full_name"
        ].lower()
    ] = node

    add_node(
        node,
        node_type=
            "power_grid_component",
        component_class=
            element[
                "class"
            ],
        name=
            element[
                "name"
            ],
        enabled=
            element[
                "enabled"
            ],
        source_dataset=
            "OpenDSS physical topology snapshot",
    )

    add_edge(
        grid_root,
        node,
        relation=
            "contains_component",
    )


    for bus in element[
        "buses"
    ]:

        if bus not in bus_lookup:
            continue

        add_edge(
            node,
            bus_lookup[
                bus
            ],
            relation=
                "connected_to_bus",
        )


# ================================================================
# CYBER / PHYSICAL BRIDGE
# ================================================================

add_edge(
    asset_lookup[
        "gridsim"
    ],
    grid_root,
    relation=
        "simulates",
    source_dataset=
        "EC-POMDG experiment design",
)


add_edge(
    asset_lookup[
        "controller"
    ],
    grid_root,
    relation=
        "controls_physical_grid",
    source_dataset=
        "EC-POMDG validated physical control path",
)


add_edge(
    asset_lookup[
        "decoy"
    ],
    grid_root,
    relation=
        "emulates_without_physical_connection",
    source_dataset=
        "EC-POMDG validated decoy isolation",
)


# ================================================================
# SMART-INVERTER IDENTIFICATION
# ================================================================

pvsystems = [
    (
        node,
        attrs,
    )
    for node, attrs
    in graph.nodes(
        data=True
    )
    if (
        attrs.get(
            "node_type"
        )
        == "power_grid_component"
        and attrs.get(
            "component_class"
        )
        == "pvsystem"
    )
]


assert pvsystems, (
    "No PVSystem found"
)


pv675 = []


for node, attrs in pvsystems:

    neighbors = {
        target
        for _, target, data
        in graph.out_edges(
            node,
            data=True,
        )
        if (
            data.get(
                "relation"
            )
            == "connected_to_bus"
        )
    }

    if (
        bus_lookup[
            "675"
        ]
        in neighbors
    ):

        pv675.append(
            node
        )


assert pv675, (
    "No PVSystem connected to bus 675"
)


for node in pv675:

    graph.nodes[
        node
    ][
        "ecpomdg_smart_inverter"
    ] = True


# Controller controls the smart inverter through gridsim.
for node in pv675:

    add_edge(
        asset_lookup[
            "controller"
        ],
        node,
        relation=
            "controls",
        protocol=
            "IEC104-to-Plant-API bridge",
        source_dataset=
            "EC-POMDG validated control path",
    )


# Decoy intentionally has no controls edge to the PVSystem.


# ================================================================
# VALIDATION
# ================================================================

print()
print(
    "===== VALIDATION ====="
)


assert len(
    asset_lookup
) == 12

print(
    "SPHERE_ASSET_COUNT: PASS"
)


assert len(
    network_lookup
) == 7

print(
    "NETWORK_SEGMENT_COUNT: PASS"
)


assert all(
    LIVE[
        "assets"
    ][
        asset
    ][
        "ok"
    ]
    for asset
    in asset_lookup
)

print(
    "LIVE_INTERFACE_MATCH: PASS"
)


assert len(
    bus_lookup
) == 16

print(
    "IEEE13_BUS_COUNT: PASS"
)


classes = Counter(
    element[
        "class"
    ]
    for element in PHYSICAL[
        "elements"
    ]
)


assert classes[
    "line"
] == 12

assert classes[
    "load"
] == 15

assert classes[
    "pvsystem"
] >= 1


print(
    "IEEE13_COMPONENT_COUNTS: PASS"
)


assert "675" in bus_lookup

assert pv675

print(
    "SMART_INVERTER_BUS675_MAPPING: PASS"
)


controller = asset_lookup[
    "controller"
]

decoy = asset_lookup[
    "decoy"
]


controller_physical_edges = [
    (
        target,
        attrs,
    )
    for _, target, attrs
    in graph.out_edges(
        controller,
        data=True,
    )
    if (
        attrs.get(
            "relation"
        )
        == "controls_physical_grid"
    )
]


decoy_physical_edges = [
    (
        target,
        attrs,
    )
    for _, target, attrs
    in graph.out_edges(
        decoy,
        data=True,
    )
    if (
        attrs.get(
            "relation"
        )
        == "controls_physical_grid"
    )
]


assert len(
    controller_physical_edges
) == 1

assert not decoy_physical_edges


print(
    "REAL_CONTROLLER_PHYSICAL_BRIDGE: PASS"
)

print(
    "DECOY_NO_PHYSICAL_CONTROL_EDGE: PASS"
)


# IEC-104 endpoint validation.
iec104_services = [
    attrs
    for _, attrs
    in graph.nodes(
        data=True
    )
    if (
        attrs.get(
            "node_type"
        )
        == "application_service"
        and attrs.get(
            "protocol"
        )
        == "IEC-60870-5-104"
    )
]


assert len(
    iec104_services
) == 2


print(
    "IEC104_REAL_DECOY_ENDPOINTS: PASS"
)


# Trusted registry must agree with topology.
assert (
    TOPOLOGY[
        "assets"
    ][
        "controller"
    ][
        "trusted_asset_id"
    ]
    == "asset-field-001"
)

assert (
    TOPOLOGY[
        "assets"
    ][
        "decoy"
    ][
        "trusted_asset_id"
    ]
    == "asset-field-002"
)


print(
    "DEFENDER_TRUSTED_ASSET_MAPPING: PASS"
)


# ================================================================
# OUTPUT
# ================================================================

RESULTS.mkdir(
    parents=True,
    exist_ok=True,
)


nodes_path = (
    RESULTS
    / "power_grid_component_topology_knowledge_graph_nodes.jsonl"
)

edges_path = (
    RESULTS
    / "power_grid_component_topology_knowledge_graph_edges.jsonl"
)

graphml_path = (
    RESULTS
    / "power_grid_component_topology_knowledge_graph.graphml"
)

summary_path = (
    RESULTS
    / "power_grid_component_topology_knowledge_graph_summary.json"
)


with nodes_path.open(
    "w",
    encoding="ascii",
) as output:

    for node, attrs in sorted(
        graph.nodes(
            data=True
        )
    ):

        output.write(
            json.dumps(
                {
                    "id":
                        node,
                    **attrs,
                },
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        )


with edges_path.open(
    "w",
    encoding="ascii",
) as output:

    edges = sorted(
        graph.edges(
            keys=True,
            data=True,
        ),
        key=lambda row: (
            row[0],
            row[1],
            str(
                row[2]
            ),
        ),
    )

    for source, target, key, attrs in edges:

        output.write(
            json.dumps(
                {
                    "source":
                        source,
                    "target":
                        target,
                    "edge_key":
                        key,
                    **attrs,
                },
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        )


nx.write_graphml(
    graph,
    graphml_path,
)


node_types = Counter(
    attrs.get(
        "node_type",
        "unknown",
    )
    for _, attrs
    in graph.nodes(
        data=True
    )
)

edge_relations = Counter(
    attrs.get(
        "relation",
        "unknown",
    )
    for _, _, attrs
    in graph.edges(
        data=True
    )
)


summary = {
    "graph_name":
        graph.graph[
            "name"
        ],

    "node_count":
        graph.number_of_nodes(),

    "edge_count":
        graph.number_of_edges(),

    "node_types":
        dict(
            sorted(
                node_types.items()
            )
        ),

    "edge_relations":
        dict(
            sorted(
                edge_relations.items()
            )
        ),

    "sphere_assets":
        len(
            asset_lookup
        ),

    "network_segments":
        len(
            network_lookup
        ),

    "grid_buses":
        len(
            bus_lookup
        ),

    "grid_component_classes":
        dict(
            sorted(
                classes.items()
            )
        ),

    "smart_inverter_nodes":
        pv675,

    "cyber_physical_bridge": {
        "real_controller":
            True,
        "decoy_controller":
            False,
    },

    "trusted_asset_mapping": {
        "controller":
            "asset-field-001",
        "decoy":
            "asset-field-002",
    },
}


summary_path.write_text(
    json.dumps(
        summary,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="ascii",
)


print()
print(
    json.dumps(
        summary,
        indent=2,
        sort_keys=True,
    )
)


print()
print(
    "=" * 68
)

print(
    "POWER_GRID_COMPONENT_TOPOLOGY_KNOWLEDGE_GRAPH: PASS"
)

print(
    "=" * 68
)
