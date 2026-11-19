#!/usr/bin/env bash

set -euo pipefail
set -o pipefail

SETUP="$HOME/ecpomdg_setup/kg_defender_integration"
AUDIT="$HOME/ecpomdg_audit/kg_defender_integration"

mkdir -p "$SETUP" "$AUDIT"

echo "================================================================"
echo " EC-POMDG UNIFIED DEFENDER KNOWLEDGE INDEX"
echo "================================================================"


# ================================================================
# 1. VERIFY ALL THREE FROZEN KNOWLEDGE GRAPHS
# ================================================================

echo
echo "===== VERIFY GENERAL CYBER KG ====="

ssh kg '
set -euo pipefail

BASE="$HOME/ecpomdg/knowledge_graphs/general_cyber"

cd /

sha256sum \
  -c \
  "$BASE/audit/general_cyber_knowledge_graph_sha256.txt"
'

echo "GENERAL_CYBER_KG_INTEGRITY: PASS"


echo
echo "===== VERIFY POWER-GRID / ICS CYBER KG ====="

ssh kg '
set -euo pipefail

BASE="$HOME/ecpomdg/knowledge_graphs/power_grid_ics_cyber"

cd /

sha256sum \
  -c \
  "$BASE/audit/power_grid_ics_cyber_knowledge_graph_sha256.txt"
'

echo "POWER_GRID_ICS_KG_INTEGRITY: PASS"


echo
echo "===== VERIFY COMPONENT + TOPOLOGY KG ====="

ssh kg '
set -euo pipefail

BASE="$HOME/ecpomdg/knowledge_graphs/power_grid_component_topology"

cd /

sha256sum \
  -c \
  "$BASE/audit/power_grid_component_topology_knowledge_graph_sha256.txt"
'

echo "COMPONENT_TOPOLOGY_KG_INTEGRITY: PASS"


# ================================================================
# 2. PREPARE INTEGRATION WORKSPACE
# ================================================================

echo
echo "===== PREPARE KG INTEGRATION WORKSPACE ====="

ssh kg '
mkdir -p \
  ~/ecpomdg/kg_defender_integration/app \
  ~/ecpomdg/kg_defender_integration/results \
  ~/ecpomdg/kg_defender_integration/audit
'


# ================================================================
# 3. BUILD UNIFIED READ-ONLY INDEX
# ================================================================

cat > "$SETUP/build_unified_defender_knowledge_index.py" <<'PY'
#!/usr/bin/env python3

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


KG_ROOT = (
    Path.home()
    / "ecpomdg"
    / "knowledge_graphs"
)

OUTPUT_ROOT = (
    Path.home()
    / "ecpomdg"
    / "kg_defender_integration"
    / "results"
)


GRAPH_PATHS = {
    "general_cyber": {
        "nodes":
            KG_ROOT
            / "general_cyber"
            / "results"
            / "general_cyber_knowledge_graph_nodes.jsonl",

        "edges":
            KG_ROOT
            / "general_cyber"
            / "results"
            / "general_cyber_knowledge_graph_edges.jsonl",

        "summary":
            KG_ROOT
            / "general_cyber"
            / "results"
            / "general_cyber_knowledge_graph_summary.json",
    },

    "power_grid_ics": {
        "nodes":
            KG_ROOT
            / "power_grid_ics_cyber"
            / "results"
            / "power_grid_ics_cyber_knowledge_graph_nodes.jsonl",

        "edges":
            KG_ROOT
            / "power_grid_ics_cyber"
            / "results"
            / "power_grid_ics_cyber_knowledge_graph_edges.jsonl",

        "summary":
            KG_ROOT
            / "power_grid_ics_cyber"
            / "results"
            / "power_grid_ics_cyber_knowledge_graph_summary.json",
    },

    "component_topology": {
        "nodes":
            KG_ROOT
            / "power_grid_component_topology"
            / "results"
            / "power_grid_component_topology_knowledge_graph_nodes.jsonl",

        "edges":
            KG_ROOT
            / "power_grid_component_topology"
            / "results"
            / "power_grid_component_topology_knowledge_graph_edges.jsonl",

        "summary":
            KG_ROOT
            / "power_grid_component_topology"
            / "results"
            / "power_grid_component_topology_knowledge_graph_summary.json",
    },
}


def load_jsonl(path):

    return [
        json.loads(line)
        for line in path.read_text(
            encoding="ascii"
        ).splitlines()
        if line.strip()
    ]


graphs = {}


for graph_name, paths in GRAPH_PATHS.items():

    nodes = load_jsonl(
        paths["nodes"]
    )

    edges = load_jsonl(
        paths["edges"]
    )

    summary = json.loads(
        paths[
            "summary"
        ].read_text(
            encoding="ascii"
        )
    )

    assert len(nodes) == summary[
        "node_count"
    ], (
        graph_name,
        len(nodes),
        summary[
            "node_count"
        ],
    )

    assert len(edges) == summary[
        "edge_count"
    ], (
        graph_name,
        len(edges),
        summary[
            "edge_count"
        ],
    )

    graphs[
        graph_name
    ] = {
        "nodes":
            nodes,
        "edges":
            edges,
        "summary":
            summary,
    }


print(
    "GENERAL CYBER:",
    len(
        graphs[
            "general_cyber"
        ][
            "nodes"
        ]
    ),
    "nodes /",
    len(
        graphs[
            "general_cyber"
        ][
            "edges"
        ]
    ),
    "edges",
)

print(
    "POWER-GRID ICS:",
    len(
        graphs[
            "power_grid_ics"
        ][
            "nodes"
        ]
    ),
    "nodes /",
    len(
        graphs[
            "power_grid_ics"
        ][
            "edges"
        ]
    ),
    "edges",
)

print(
    "COMPONENT TOPOLOGY:",
    len(
        graphs[
            "component_topology"
        ][
            "nodes"
        ]
    ),
    "nodes /",
    len(
        graphs[
            "component_topology"
        ][
            "edges"
        ]
    ),
    "edges",
)


# ================================================================
# NODE LOOKUPS
# ================================================================

nodes_by_graph = {}

for graph_name, graph in graphs.items():

    nodes_by_graph[
        graph_name
    ] = {
        row["id"]:
            row
        for row in graph[
            "nodes"
        ]
    }


# ================================================================
# GENERAL CYBER EXTERNAL-ID INDEX
# ================================================================

general_external_ids = defaultdict(
    list
)

for node in graphs[
    "general_cyber"
][
    "nodes"
]:

    external_id = node.get(
        "external_id"
    )

    if external_id:

        general_external_ids[
            str(
                external_id
            )
        ].append(
            node["id"]
        )


# ================================================================
# ICS EXTERNAL-ID INDEX
# ================================================================

ics_external_ids = defaultdict(
    list
)

for node in graphs[
    "power_grid_ics"
][
    "nodes"
]:

    external_id = node.get(
        "external_id"
    )

    if external_id:

        ics_external_ids[
            str(
                external_id
            )
        ].append(
            node["id"]
        )


# ================================================================
# CROSS-GRAPH SHARED IDENTIFIERS
#
# We only link exact external identifiers.
# No semantic similarity or guessed equivalence is used.
# ================================================================

cross_graph_links = []


shared_external_ids = sorted(
    set(
        general_external_ids
    )
    &
    set(
        ics_external_ids
    )
)


for external_id in shared_external_ids:

    for general_node in general_external_ids[
        external_id
    ]:

        for ics_node in ics_external_ids[
            external_id
        ]:

            cross_graph_links.append({
                "source_graph":
                    "general_cyber",

                "source_node":
                    general_node,

                "target_graph":
                    "power_grid_ics",

                "target_node":
                    ics_node,

                "relation":
                    "same_external_identifier",

                "external_id":
                    external_id,
            })


# ================================================================
# TRUSTED ASSET CONTEXT
# ================================================================

asset_context = {}


for node in graphs[
    "component_topology"
][
    "nodes"
]:

    if (
        node.get(
            "node_type"
        )
        != "cyber_asset"
    ):
        continue

    trusted_asset_id = node.get(
        "trusted_asset_id"
    )

    if not trusted_asset_id:
        continue

    asset_context[
        trusted_asset_id
    ] = {
        "topology_node":
            node["id"],

        "hostname":
            node.get(
                "hostname",
                "",
            ),

        "role":
            node.get(
                "role",
                "",
            ),

        "physical_grid_connected":
            node.get(
                "physical_grid_connected"
            ),
    }


assert (
    "asset-field-001"
    in asset_context
)

assert (
    "asset-field-002"
    in asset_context
)


assert (
    asset_context[
        "asset-field-001"
    ][
        "physical_grid_connected"
    ]
    is True
)


assert (
    asset_context[
        "asset-field-002"
    ][
        "physical_grid_connected"
    ]
    is False
)


# ================================================================
# IEC-104 SERVICES IN TOPOLOGY KG
# ================================================================

iec104_services = []


for node in graphs[
    "component_topology"
][
    "nodes"
]:

    if (
        node.get(
            "node_type"
        )
        == "application_service"
        and
        node.get(
            "protocol"
        )
        == "IEC-60870-5-104"
    ):

        iec104_services.append({
            "node_id":
                node["id"],

            "name":
                node.get(
                    "name",
                    "",
                ),

            "endpoint":
                node.get(
                    "endpoint",
                    "",
                ),
        })


assert len(
    iec104_services
) == 2


# ================================================================
# SMART INVERTER
# ================================================================

smart_inverters = []


for node in graphs[
    "component_topology"
][
    "nodes"
]:

    if (
        node.get(
            "node_type"
        )
        == "power_grid_component"
        and
        node.get(
            "ecpomdg_smart_inverter"
        )
        is True
    ):

        smart_inverters.append(
            node["id"]
        )


assert len(
    smart_inverters
) >= 1


# ================================================================
# ICS PROTOCOL + CONTROL POINTS
# ================================================================

ics_protocol_nodes = []

control_points = {}


for node in graphs[
    "power_grid_ics"
][
    "nodes"
]:

    if (
        node.get(
            "node_type"
        )
        == "industrial_protocol"
        and
        node.get(
            "external_id"
        )
        == "IEC-60870-5-104"
    ):

        ics_protocol_nodes.append(
            node["id"]
        )


    if (
        node.get(
            "node_type"
        )
        == "iec104_control_point"
    ):

        ioa = int(
            node[
                "ioa"
            ]
        )

        control_points[
            ioa
        ] = {
            "node_id":
                node["id"],

            "name":
                node.get(
                    "name",
                    "",
                ),

            "quantity":
                node.get(
                    "quantity",
                    "",
                ),
        }


assert len(
    ics_protocol_nodes
) == 1

assert 100 in control_points
assert 101 in control_points


# ================================================================
# BEHAVIOR -> ATT&CK TECHNIQUE INDEX
# ================================================================

ics_nodes = nodes_by_graph[
    "power_grid_ics"
]


behavior_techniques = defaultdict(
    list
)


for edge in graphs[
    "power_grid_ics"
][
    "edges"
]:

    if (
        edge.get(
            "relation"
        )
        != "maps_to_attack_technique"
    ):
        continue

    source = edge[
        "source"
    ]

    target = edge[
        "target"
    ]

    source_node = ics_nodes.get(
        source,
        {}
    )

    target_node = ics_nodes.get(
        target,
        {}
    )

    if (
        source_node.get(
            "node_type"
        )
        != "experiment_behavior"
    ):
        continue

    external_id = target_node.get(
        "external_id"
    )

    if not external_id:
        continue

    behavior_techniques[
        source
    ].append({
        "technique_node":
            target,

        "technique_id":
            external_id,

        "technique_name":
            target_node.get(
                "name",
                "",
            ),
    })


for behavior in behavior_techniques:

    behavior_techniques[
        behavior
    ] = sorted(
        behavior_techniques[
            behavior
        ],
        key=lambda x:
            x[
                "technique_id"
            ],
    )


# ================================================================
# TECHNIQUE -> THREAT SOFTWARE CONTEXT
#
# Native ATT&CK "uses" relationships only.
# ================================================================

technique_software = defaultdict(
    list
)


for edge in graphs[
    "power_grid_ics"
][
    "edges"
]:

    if (
        edge.get(
            "relation"
        )
        != "uses"
    ):
        continue

    source = ics_nodes.get(
        edge[
            "source"
        ],
        {},
    )

    target = ics_nodes.get(
        edge[
            "target"
        ],
        {},
    )

    if (
        source.get(
            "node_type"
        )
        not in {
            "ics_malware",
            "ics_tool",
        }
    ):
        continue

    technique_id = target.get(
        "external_id"
    )

    if not technique_id:
        continue

    technique_software[
        technique_id
    ].append({
        "node_id":
            source[
                "id"
            ],

        "external_id":
            source.get(
                "external_id",
                "",
            ),

        "name":
            source.get(
                "name",
                "",
            ),
    })


# ================================================================
# RUNTIME OBSERVATION RULES
#
# These provide CONTEXT, not an attack verdict.
# A matching event is not automatically malicious.
# ================================================================

observation_rules = [
    {
        "rule_id":
            "iec104-active-power-command-context",

        "match": {
            "protocol":
                "IEC104",

            "event_type":
                "iec104_execute",

            "ioa":
                100,

            "quantity":
                "p_kw",
        },

        "control_point":
            control_points[
                100
            ],

        "behavior_nodes": [
            "BEHAVIOR::select-execute-command",
            "BEHAVIOR::active-power-setpoint-manipulation",
        ],
    },

    {
        "rule_id":
            "iec104-reactive-power-command-context",

        "match": {
            "protocol":
                "IEC104",

            "event_type":
                "iec104_execute",

            "ioa":
                101,

            "quantity":
                "q_kvar",
        },

        "control_point":
            control_points[
                101
            ],

        "behavior_nodes": [
            "BEHAVIOR::select-execute-command",
            "BEHAVIOR::reactive-power-setpoint-manipulation",
        ],
    },
]


for rule in observation_rules:

    techniques = {}

    for behavior_node in rule[
        "behavior_nodes"
    ]:

        for technique in behavior_techniques.get(
            behavior_node,
            [],
        ):

            techniques[
                technique[
                    "technique_id"
                ]
            ] = technique


    rule[
        "attack_context"
    ] = [
        techniques[key]
        for key in sorted(
            techniques
        )
    ]


    software = {}

    for technique in rule[
        "attack_context"
    ]:

        technique_id = technique[
            "technique_id"
        ]

        for item in technique_software.get(
            technique_id,
            [],
        ):

            key = (
                item.get(
                    "external_id"
                )
                or
                item[
                    "node_id"
                ]
            )

            software[
                key
            ] = item


    rule[
        "known_ics_software_context"
    ] = [
        software[key]
        for key in sorted(
            software
        )
    ]


# ================================================================
# EXPLICIT CROSS-LINKS
# ================================================================

for protocol_node in ics_protocol_nodes:

    for service in iec104_services:

        cross_graph_links.append({
            "source_graph":
                "power_grid_ics",

            "source_node":
                protocol_node,

            "target_graph":
                "component_topology",

            "target_node":
                service[
                    "node_id"
                ],

            "relation":
                "implemented_by_service",
        })


for ioa, point in sorted(
    control_points.items()
):

    for inverter_node in smart_inverters:

        cross_graph_links.append({
            "source_graph":
                "power_grid_ics",

            "source_node":
                point[
                    "node_id"
                ],

            "target_graph":
                "component_topology",

            "target_node":
                inverter_node,

            "relation":
                "controls_component_in_experiment",

            "ioa":
                ioa,
        })


for trusted_id, context in sorted(
    asset_context.items()
):

    cross_graph_links.append({
        "source_graph":
            "operational_defender_view",

        "source_node":
            trusted_id,

        "target_graph":
            "component_topology",

        "target_node":
            context[
                "topology_node"
            ],

        "relation":
            "resolves_to_topology_asset",
    })


# ================================================================
# FINAL INDEX
# ================================================================

index = {
    "schema_version":
        1,

    "built_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "purpose":
        (
            "Read-only contextual index for enriching "
            "EC-POMDG defender observations. "
            "The index provides knowledge context and "
            "does not determine whether an observation "
            "is malicious."
        ),

    "source_graphs": {
        graph_name: {
            "node_count":
                len(
                    graph[
                        "nodes"
                    ]
                ),

            "edge_count":
                len(
                    graph[
                        "edges"
                    ]
                ),
        }

        for graph_name, graph
        in graphs.items()
    },

    "trusted_asset_context":
        asset_context,

    "iec104_services":
        iec104_services,

    "smart_inverter_nodes":
        smart_inverters,

    "iec104_control_points":
        {
            str(key):
                value

            for key, value
            in sorted(
                control_points.items()
            )
        },

    "observation_context_rules":
        observation_rules,

    "shared_external_identifier_count":
        len(
            shared_external_ids
        ),

    "shared_external_identifiers":
        shared_external_ids,

    "cross_graph_links":
        cross_graph_links,
}


OUTPUT_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


index_path = (
    OUTPUT_ROOT
    / "unified_defender_knowledge_index.json"
)

links_path = (
    OUTPUT_ROOT
    / "unified_defender_cross_graph_links.jsonl"
)

summary_path = (
    OUTPUT_ROOT
    / "unified_defender_knowledge_index_summary.json"
)


index_path.write_text(
    json.dumps(
        index,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="ascii",
)


with links_path.open(
    "w",
    encoding="ascii",
) as output:

    for link in cross_graph_links:

        output.write(
            json.dumps(
                link,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        )


summary = {
    "schema_version":
        1,

    "source_graphs":
        index[
            "source_graphs"
        ],

    "trusted_asset_count":
        len(
            asset_context
        ),

    "iec104_service_count":
        len(
            iec104_services
        ),

    "iec104_control_point_count":
        len(
            control_points
        ),

    "smart_inverter_count":
        len(
            smart_inverters
        ),

    "observation_context_rule_count":
        len(
            observation_rules
        ),

    "cross_graph_link_count":
        len(
            cross_graph_links
        ),

    "shared_external_identifier_count":
        len(
            shared_external_ids
        ),
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


# ================================================================
# VALIDATION
# ================================================================

print()
print(
    "===== UNIFIED INDEX VALIDATION ====="
)


assert (
    index[
        "source_graphs"
    ][
        "general_cyber"
    ][
        "node_count"
    ]
    >= 6000
)

assert (
    index[
        "source_graphs"
    ][
        "general_cyber"
    ][
        "edge_count"
    ]
    >= 31000
)


assert (
    index[
        "source_graphs"
    ][
        "power_grid_ics"
    ][
        "node_count"
    ]
    == 467
)

assert (
    index[
        "source_graphs"
    ][
        "power_grid_ics"
    ][
        "edge_count"
    ]
    == 1800
)


assert (
    index[
        "source_graphs"
    ][
        "component_topology"
    ][
        "node_count"
    ]
    == 104
)

assert (
    index[
        "source_graphs"
    ][
        "component_topology"
    ][
        "edge_count"
    ]
    == 176
)


print(
    "ALL_THREE_FROZEN_KGS_LOADED: PASS"
)


assert (
    index[
        "trusted_asset_context"
    ][
        "asset-field-001"
    ][
        "role"
    ]
    == "real_controller"
)

assert (
    index[
        "trusted_asset_context"
    ][
        "asset-field-002"
    ][
        "role"
    ]
    == "decoy_controller"
)


print(
    "TRUSTED_REAL_DECOY_ASSET_CONTEXT: PASS"
)


assert len(
    index[
        "iec104_services"
    ]
) == 2

assert (
    "100"
    in index[
        "iec104_control_points"
    ]
)

assert (
    "101"
    in index[
        "iec104_control_points"
    ]
)


print(
    "IEC104_PROTOCOL_CONTEXT: PASS"
)


assert index[
    "smart_inverter_nodes"
]


print(
    "SMART_INVERTER_CONTEXT: PASS"
)


expected_techniques = {
    "T0831",
    "T0836",
    "T1692.001",
}


for rule in observation_rules:

    technique_ids = {
        row[
            "technique_id"
        ]
        for row in rule[
            "attack_context"
        ]
    }

    assert expected_techniques.issubset(
        technique_ids
    ), (
        rule[
            "rule_id"
        ],
        technique_ids,
    )


print(
    "IEC104_ATTACK_CONTEXT_MAPPING: PASS"
)


# The current runtime rules must not claim brute-force IO.
for rule in observation_rules:

    ids = {
        row[
            "technique_id"
        ]
        for row in rule[
            "attack_context"
        ]
    }

    assert "T0806" not in ids


print(
    "NO_FALSE_BRUTE_FORCE_IO_RUNTIME_MAPPING: PASS"
)


# The index must never contain experiment oracle records.
FORBIDDEN_KEYS = {
    "raw_event",
    "attack_success",
    "ground_truth",
    "physical_effect",
}


def audit_keys(value):

    if isinstance(
        value,
        dict,
    ):

        for key, child in value.items():

            assert key not in FORBIDDEN_KEYS, (
                f"Forbidden oracle key in index: {key}"
            )

            audit_keys(
                child
            )

    elif isinstance(
        value,
        list,
    ):

        for child in value:

            audit_keys(
                child
            )


audit_keys(
    index
)


print(
    "ORACLE_DATA_NOT_IMPORTED: PASS"
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
    "UNIFIED_DEFENDER_KNOWLEDGE_INDEX: PASS"
)

print(
    "=" * 68
)
PY


# ================================================================
# 4. SYNTAX CHECK
# ================================================================

echo
echo "===== BUILDER SYNTAX ====="

python3 \
  -m py_compile \
  "$SETUP/build_unified_defender_knowledge_index.py"

echo \
  "UNIFIED_INDEX_BUILDER_SYNTAX: PASS"


# ================================================================
# 5. DEPLOY
# ================================================================

scp \
  "$SETUP/build_unified_defender_knowledge_index.py" \
  kg:~/ecpomdg/kg_defender_integration/app/


# ================================================================
# 6. BUILD
# ================================================================

echo
echo "===== BUILD UNIFIED DEFENDER KNOWLEDGE INDEX ====="

ssh kg '
set -euo pipefail

VENV="$HOME/ecpomdg/venvs/knowledge_graphs"
BASE="$HOME/ecpomdg/kg_defender_integration"

PYTHONIOENCODING=UTF-8 \
"$VENV/bin/python" \
  "$BASE/app/build_unified_defender_knowledge_index.py" \
  | tee \
  "$BASE/results/unified_defender_knowledge_index_build.log"
'


# ================================================================
# 7. INDEPENDENT VALIDATION
# ================================================================

echo
echo "===== INDEPENDENT INDEX VALIDATION ====="

ssh kg python3 - <<'PY'
import json
from pathlib import Path

ROOT = (
    Path.home()
    / "ecpomdg"
    / "kg_defender_integration"
    / "results"
)

index = json.loads(
    (
        ROOT
        / "unified_defender_knowledge_index.json"
    ).read_text(
        encoding="ascii"
    )
)

summary = json.loads(
    (
        ROOT
        / "unified_defender_knowledge_index_summary.json"
    ).read_text(
        encoding="ascii"
    )
)


assert (
    index[
        "trusted_asset_context"
    ][
        "asset-field-001"
    ][
        "physical_grid_connected"
    ]
    is True
)

assert (
    index[
        "trusted_asset_context"
    ][
        "asset-field-002"
    ][
        "physical_grid_connected"
    ]
    is False
)


assert summary[
    "observation_context_rule_count"
] == 2


assert summary[
    "iec104_control_point_count"
] == 2


print(
    "REAL_CONTROLLER_CONTEXT: PASS"
)

print(
    "DECOY_CONTROLLER_CONTEXT: PASS"
)

print(
    "OBSERVATION_RULE_COUNT: PASS"
)

print(
    "UNIFIED_INDEX_INDEPENDENT_VALIDATION: PASS"
)
PY


# ================================================================
# 8. FREEZE
# ================================================================

echo
echo "===== FREEZE UNIFIED INDEX ====="

ssh kg '
set -euo pipefail

BASE="$HOME/ecpomdg/kg_defender_integration"

sha256sum \
  "$BASE/app/build_unified_defender_knowledge_index.py" \
  "$BASE/results/unified_defender_knowledge_index.json" \
  "$BASE/results/unified_defender_cross_graph_links.jsonl" \
  "$BASE/results/unified_defender_knowledge_index_summary.json" \
  "$BASE/results/unified_defender_knowledge_index_build.log" \
  > \
  "$BASE/audit/unified_defender_knowledge_index_sha256.txt"

cat \
  "$BASE/audit/unified_defender_knowledge_index_sha256.txt"
'


# ================================================================
# 9. COPY AUDIT ARTIFACTS
# ================================================================

echo
echo "===== COPY AUDIT ARTIFACTS ====="

scp \
  kg:~/ecpomdg/kg_defender_integration/results/unified_defender_knowledge_index_summary.json \
  "$AUDIT/"

scp \
  kg:~/ecpomdg/kg_defender_integration/results/unified_defender_knowledge_index_build.log \
  "$AUDIT/"

scp \
  kg:~/ecpomdg/kg_defender_integration/audit/unified_defender_knowledge_index_sha256.txt \
  "$AUDIT/"


echo
echo "================================================================"
echo "UNIFIED_DEFENDER_KNOWLEDGE_INDEX_BUILD: PASS"
echo "================================================================"

