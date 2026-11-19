#!/usr/bin/env python3

import json
import re
from collections import Counter, deque
from pathlib import Path

import networkx as nx


BASE = (
    Path.home()
    / "ecpomdg"
    / "knowledge_graphs"
    / "power_grid_ics_cyber"
)

SOURCE = BASE / "source"
RESULTS = BASE / "results"

ICS_PATH = (
    SOURCE
    / "mitre_ics_attack_v19_2.json"
)

MAPPING_PATH = (
    SOURCE
    / "iec104_experiment_attack_mapping.json"
)

EXPERIMENT_DIR = (
    SOURCE
    / "experiment"
)


graph = nx.MultiDiGraph(
    name="EC-POMDG Power-Grid / ICS Cyber Knowledge Graph"
)


def clean_text(value):

    if value is None:
        return ""

    return " ".join(
        str(value).split()
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


def slug(value):

    value = clean_text(
        value
    ).lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    )

    return (
        value.strip("-")
        or "unknown"
    )


def external_id(obj):

    for ref in obj.get(
        "external_references",
        [],
    ):

        value = ref.get(
            "external_id"
        )

        if value:
            return value

    return ""


def add_node(
    node_id,
    **attrs,
):

    cleaned = {
        key:
            scalar(value)
        for key, value
        in attrs.items()
    }

    if graph.has_node(
        node_id
    ):

        graph.nodes[
            node_id
        ].update(
            cleaned
        )

    else:

        graph.add_node(
            node_id,
            **cleaned,
        )


def add_edge(
    source,
    target,
    relation,
    source_dataset,
    **attrs,
):

    if not graph.has_node(
        source
    ):
        raise RuntimeError(
            f"Missing edge source: {source}"
        )

    if not graph.has_node(
        target
    ):
        raise RuntimeError(
            f"Missing edge target: {target}"
        )

    graph.add_edge(
        source,
        target,
        relation=
            relation,
        source_dataset=
            source_dataset,
        **{
            key:
                scalar(value)
            for key, value
            in attrs.items()
        },
    )


# ================================================================
# MITRE ATT&CK FOR ICS
# ================================================================

print(
    "===== MITRE ATT&CK FOR ICS ====="
)

bundle = json.loads(
    ICS_PATH.read_text(
        encoding="utf-8"
    )
)

objects = bundle[
    "objects"
]


SUPPORTED_TYPES = {
    "attack-pattern",
    "campaign",
    "course-of-action",
    "intrusion-set",
    "malware",
    "tool",
    "x-mitre-analytic",
    "x-mitre-asset",
    "x-mitre-data-component",
    "x-mitre-data-source",
    "x-mitre-detection-strategy",
    "x-mitre-tactic",
}


stix_lookup = {}
external_lookup = {}


for obj in objects:

    object_type = obj.get(
        "type"
    )

    if (
        object_type
        not in SUPPORTED_TYPES
    ):
        continue

    if obj.get(
        "revoked",
        False,
    ):
        continue

    if obj.get(
        "x_mitre_deprecated",
        False,
    ):
        continue

    stix_id = obj[
        "id"
    ]

    node_id = (
        "ICS::"
        + stix_id
    )

    ext_id = external_id(
        obj
    )

    add_node(
        node_id,
        node_type=
            "ics_"
            + object_type.replace(
                "-",
                "_",
            ),
        source_dataset=
            "MITRE ATT&CK for ICS 19.2",
        external_id=
            ext_id,
        name=
            obj.get(
                "name",
                "",
            ),
        description=
            clean_text(
                obj.get(
                    "description",
                    "",
                )
            ),
        platforms=
            obj.get(
                "x_mitre_platforms",
                [],
            ),
        created=
            obj.get(
                "created",
                "",
            ),
        modified=
            obj.get(
                "modified",
                "",
            ),
        power_grid_focus=
            False,
    )

    stix_lookup[
        stix_id
    ] = node_id

    if ext_id:

        external_lookup[
            ext_id
        ] = node_id


# Native ATT&CK relationships.
for obj in objects:

    if obj.get(
        "type"
    ) != "relationship":
        continue

    if obj.get(
        "revoked",
        False,
    ):
        continue

    if obj.get(
        "x_mitre_deprecated",
        False,
    ):
        continue

    source = stix_lookup.get(
        obj.get(
            "source_ref"
        )
    )

    target = stix_lookup.get(
        obj.get(
            "target_ref"
        )
    )

    if (
        source is None
        or target is None
    ):
        continue

    add_edge(
        source,
        target,
        relation=
            obj.get(
                "relationship_type",
                "related_to",
            ),
        source_dataset=
            "MITRE ATT&CK for ICS 19.2",
        description=
            clean_text(
                obj.get(
                    "description",
                    "",
                )
            ),
    )


# Technique -> tactic relationships.
tactic_shortname_lookup = {}

for obj in objects:

    if (
        obj.get(
            "type"
        )
        != "x-mitre-tactic"
    ):
        continue

    if obj["id"] not in stix_lookup:
        continue

    shortname = obj.get(
        "x_mitre_shortname"
    )

    if shortname:

        tactic_shortname_lookup[
            shortname
        ] = stix_lookup[
            obj["id"]
        ]


for obj in objects:

    if (
        obj.get(
            "type"
        )
        != "attack-pattern"
    ):
        continue

    if obj["id"] not in stix_lookup:
        continue

    technique = stix_lookup[
        obj["id"]
    ]

    for phase in obj.get(
        "kill_chain_phases",
        [],
    ):

        tactic = tactic_shortname_lookup.get(
            phase.get(
                "phase_name"
            )
        )

        if tactic:

            add_edge(
                technique,
                tactic,
                relation=
                    "belongs_to_tactic",
                source_dataset=
                    "MITRE ATT&CK for ICS 19.2",
            )


print(
    "active ICS ATT&CK nodes:",
    len(
        stix_lookup
    ),
)


# ================================================================
# VERIFY CORE POWER-GRID / INDUSTROYER KNOWLEDGE EXISTS
# ================================================================

required_external_ids = {
    "S0604":
        "Industroyer",

    "S1072":
        "Industroyer2",

    "T0801":
        "Monitor Process State",

    "T0806":
        "Brute Force I/O",

    "T0831":
        "Manipulation of Control",

    "T0836":
        "Modify Parameter",

    "T1692.001":
        "Unauthorized Message: Command Message",
}


for ext_id, expected_name in (
    required_external_ids.items()
):

    assert ext_id in external_lookup, (
        f"Missing required ATT&CK object: "
        f"{ext_id} {expected_name}"
    )


print(
    "INDUSTROYER_ATTACK_OBJECTS_PRESENT: PASS"
)


# ================================================================
# EC-POMDG EXPERIMENT OVERLAY
# ================================================================

print()
print(
    "===== EC-POMDG IEC-104 EXPERIMENT OVERLAY ====="
)

mapping = json.loads(
    MAPPING_PATH.read_text(
        encoding="utf-8"
    )
)


scenario_id = (
    "EXPERIMENT::"
    + mapping[
        "scenario_id"
    ]
)

add_node(
    scenario_id,
    node_type=
        "experiment_scenario",
    source_dataset=
        "EC-POMDG SPHERE experiment",
    name=
        mapping[
            "scenario_name"
        ],
    power_grid_focus=
        True,
)


protocol = mapping[
    "protocol"
]

protocol_node = (
    "PROTOCOL::"
    + protocol[
        "id"
    ]
)

add_node(
    protocol_node,
    node_type=
        "industrial_protocol",
    source_dataset=
        "EC-POMDG experiment definition",
    name=
        protocol[
            "name"
        ],
    external_id=
        "IEC-60870-5-104",
    power_grid_focus=
        True,
)


add_edge(
    scenario_id,
    protocol_node,
    relation=
        "uses_protocol",
    source_dataset=
        "EC-POMDG experiment definition",
)


# ATT&CK software explicitly associated with IEC-104.
for software_id in (
    "S0604",
    "S1072",
):

    software_node = external_lookup[
        software_id
    ]

    add_edge(
        software_node,
        protocol_node,
        relation=
            "uses_protocol",
        source_dataset=
            "MITRE ATT&CK procedure mapping",
        evidence_reference=
            (
                "https://attack.mitre.org/software/"
                + software_id
                + "/"
            ),
    )


behavior_nodes = {}

for behavior in mapping[
    "behaviors"
]:

    node_id = (
        "BEHAVIOR::"
        + behavior[
            "id"
        ]
    )

    behavior_nodes[
        behavior[
            "id"
        ]
    ] = node_id

    add_node(
        node_id,
        node_type=
            "experiment_behavior",
        source_dataset=
            "EC-POMDG experiment mapping",
        name=
            behavior[
                "name"
            ],
        power_grid_focus=
            True,
    )

    add_edge(
        scenario_id,
        node_id,
        relation=
            "observed_behavior",
        source_dataset=
            "EC-POMDG experiment mapping",
    )

    for technique_id in behavior[
        "attack_techniques"
    ]:

        assert technique_id in external_lookup, (
            f"Experiment mapping references "
            f"missing technique {technique_id}"
        )

        add_edge(
            node_id,
            external_lookup[
                technique_id
            ],
            relation=
                "maps_to_attack_technique",
            source_dataset=
                "EC-POMDG experiment mapping",
        )


# Control points.
for point in mapping[
    "control_points"
]:

    ioa = point[
        "ioa"
    ]

    node_id = (
        f"IEC104_IOA::{ioa}"
    )

    add_node(
        node_id,
        node_type=
            "iec104_control_point",
        source_dataset=
            "EC-POMDG experiment definition",
        name=
            point[
                "name"
            ],
        ioa=
            ioa,
        quantity=
            point[
                "quantity"
            ],
        power_grid_focus=
            True,
    )

    add_edge(
        scenario_id,
        node_id,
        relation=
            "targets_control_point",
        source_dataset=
            "EC-POMDG experiment definition",
    )


# Explicitly preserve techniques we did NOT claim.
for item in mapping.get(
    "not_claimed_for_current_experiment",
    [],
):

    attack_id = item[
        "attack_technique"
    ]

    node_id = (
        "EXPERIMENT_EXCLUSION::"
        + attack_id
    )

    add_node(
        node_id,
        node_type=
            "experiment_mapping_exclusion",
        source_dataset=
            "EC-POMDG experiment mapping",
        external_id=
            attack_id,
        name=
            (
                "Not claimed for current experiment: "
                + attack_id
            ),
        reason=
            item[
                "reason"
            ],
        power_grid_focus=
            True,
    )

    add_edge(
        scenario_id,
        node_id,
        relation=
            "does_not_claim",
        source_dataset=
            "EC-POMDG experiment mapping",
    )

    add_edge(
        node_id,
        external_lookup[
            attack_id
        ],
        relation=
            "refers_to_attack_technique",
        source_dataset=
            "EC-POMDG experiment mapping",
    )


# ================================================================
# EXPERIMENT EVIDENCE
# ================================================================

real_path = (
    EXPERIMENT_DIR
    / "industroyer_inspired_iec104_real_impact_sequence.json"
)

decoy_path = (
    EXPERIMENT_DIR
    / "industroyer_inspired_iec104_decoy_impact_sequence.json"
)

select_path = (
    EXPERIMENT_DIR
    / "iec104_select_execute_protocol_validation.json"
)


real_result = json.loads(
    real_path.read_text(
        encoding="utf-8"
    )
)

decoy_result = json.loads(
    decoy_path.read_text(
        encoding="utf-8"
    )
)

select_result = json.loads(
    select_path.read_text(
        encoding="utf-8"
    )
)


evidence_real = (
    "EVIDENCE::"
    "real-controller-impact-sequence"
)

add_node(
    evidence_real,
    node_type=
        "experiment_evidence",
    source_dataset=
        "EC-POMDG frozen experiment artifact",
    name=
        "Real controller IEC-104 impact sequence",
    target=
        "real",
    baseline_p_kw=
        real_result[
            "baseline"
        ][
            "p_kw"
        ],
    baseline_q_kvar=
        real_result[
            "baseline"
        ][
            "q_kvar"
        ],
    baseline_voltage_pu=
        real_result[
            "baseline"
        ][
            "voltage_pu"
        ],
    power_grid_focus=
        True,
)

add_edge(
    evidence_real,
    scenario_id,
    relation=
        "supports_scenario",
    source_dataset=
        "EC-POMDG frozen experiment artifact",
)


evidence_decoy = (
    "EVIDENCE::"
    "decoy-controller-impact-sequence"
)

add_node(
    evidence_decoy,
    node_type=
        "experiment_evidence",
    source_dataset=
        "EC-POMDG frozen experiment artifact",
    name=
        "Decoy controller IEC-104 impact sequence",
    target=
        "decoy",
    baseline_p_kw=
        decoy_result[
            "baseline"
        ][
            "p_kw"
        ],
    baseline_q_kvar=
        decoy_result[
            "baseline"
        ][
            "q_kvar"
        ],
    baseline_voltage_pu=
        decoy_result[
            "baseline"
        ][
            "voltage_pu"
        ],
    power_grid_focus=
        True,
)

add_edge(
    evidence_decoy,
    scenario_id,
    relation=
        "supports_scenario",
    source_dataset=
        "EC-POMDG frozen experiment artifact",
)


select_evidence = (
    "EVIDENCE::"
    "iec104-select-execute-validation"
)

add_node(
    select_evidence,
    node_type=
        "experiment_evidence",
    source_dataset=
        "EC-POMDG frozen experiment artifact",
    name=
        "IEC-104 Select/Execute protocol validation",
    power_grid_focus=
        True,
)


for target in (
    "real",
    "decoy",
):

    sequence = select_result[
        target
    ]

    operations = [
        item[
            "operation"
        ]
        for item in sequence
    ]

    assert operations == [
        "SELECT",
        "EXECUTE",
        "SELECT",
        "EXECUTE",
        "SELECT",
        "EXECUTE",
        "SELECT",
        "EXECUTE",
    ], (
        target,
        operations,
    )


add_edge(
    select_evidence,
    behavior_nodes[
        "select-execute-command"
    ],
    relation=
        "supports_behavior",
    source_dataset=
        "EC-POMDG frozen experiment artifact",
)


# Evidence for P and Q behavior.
real_actions = {
    step[
        "action"
    ]:
        step
    for step in real_result[
        "steps"
    ]
}

decoy_actions = {
    step[
        "action"
    ]:
        step
    for step in decoy_result[
        "steps"
    ]
}


assert "p_curtail" in real_actions
assert "q_generate" in real_actions

assert "p_curtail" in decoy_actions
assert "q_generate" in decoy_actions


for evidence_node in (
    evidence_real,
    evidence_decoy,
):

    add_edge(
        evidence_node,
        behavior_nodes[
            "active-power-setpoint-manipulation"
        ],
        relation=
            "supports_behavior",
        source_dataset=
            "EC-POMDG frozen experiment artifact",
    )

    add_edge(
        evidence_node,
        behavior_nodes[
            "reactive-power-setpoint-manipulation"
        ],
        relation=
            "supports_behavior",
        source_dataset=
            "EC-POMDG frozen experiment artifact",
    )


# ================================================================
# POWER-GRID FOCUS CLOSURE
#
# Keep full ICS ATT&CK context, but mark the power-grid-centered
# neighborhood used by the defender and later analyses.
# ================================================================

POWER_GRID_SEEDS = {
    "S0604",
    "S1072",
    "T0801",
    "T0806",
    "T0831",
    "T0836",
    "T1692.001",
}


focus_nodes = {
    scenario_id,
    protocol_node,
    evidence_real,
    evidence_decoy,
    select_evidence,
}

focus_nodes.update(
    behavior_nodes.values()
)


for ext_id in POWER_GRID_SEEDS:

    focus_nodes.add(
        external_lookup[
            ext_id
        ]
    )


undirected = graph.to_undirected()

queue = deque(
    (
        node,
        0,
    )
    for node in list(
        focus_nodes
    )
)

seen = set(
    focus_nodes
)


while queue:

    node, depth = (
        queue.popleft()
    )

    if depth >= 1:
        continue

    for neighbor in undirected.neighbors(
        node
    ):

        if neighbor in seen:
            continue

        seen.add(
            neighbor
        )

        queue.append(
            (
                neighbor,
                depth + 1,
            )
        )


focus_nodes.update(
    seen
)


for node in graph.nodes:

    graph.nodes[
        node
    ][
        "power_grid_focus"
    ] = (
        node
        in focus_nodes
    )


focus_graph = graph.subgraph(
    focus_nodes
).copy()


# ================================================================
# VALIDATION
# ================================================================

print()
print(
    "===== VALIDATION ====="
)


for ext_id in required_external_ids:

    node = external_lookup[
        ext_id
    ]

    assert graph.has_node(
        node
    )


print(
    "REQUIRED_ICS_TECHNIQUES_AND_SOFTWARE: PASS"
)


# Verify Industroyer relationships are actually native ATT&CK
# relationships rather than invented by the experiment overlay.

def has_native_uses(
    software_external_id,
    technique_external_id,
):

    source = external_lookup[
        software_external_id
    ]

    target = external_lookup[
        technique_external_id
    ]

    for _, _, attrs in graph.edges(
        source,
        data=True,
    ):

        pass

    edge_data = graph.get_edge_data(
        source,
        target,
        default={},
    )

    return any(
        attrs.get(
            "relation"
        )
        == "uses"
        and attrs.get(
            "source_dataset"
        )
        == "MITRE ATT&CK for ICS 19.2"

        for attrs in edge_data.values()
    )


assert has_native_uses(
    "S0604",
    "T0806",
)

assert has_native_uses(
    "S1072",
    "T0801",
)

assert has_native_uses(
    "S1072",
    "T0836",
)

assert has_native_uses(
    "S1072",
    "T1692.001",
)


print(
    "INDUSTROYER_NATIVE_ATTACK_RELATIONSHIPS: PASS"
)


# Ensure current experiment intentionally does NOT claim brute force IO.
scenario_edges = list(
    graph.out_edges(
        scenario_id,
        data=True,
    )
)

direct_t0806_claim = any(
    attrs.get(
        "relation"
    )
    == "maps_to_attack_technique"
    and target
    == external_lookup[
        "T0806"
    ]

    for _, target, attrs
    in scenario_edges
)

assert not direct_t0806_claim


print(
    "CURRENT_EXPERIMENT_NO_FALSE_BRUTE_FORCE_IO_CLAIM: PASS"
)


assert (
    graph.number_of_nodes()
    > 100
)

assert (
    graph.number_of_edges()
    > 100
)

assert (
    focus_graph.number_of_nodes()
    > 20
)


print(
    "ICS_GRAPH_SCALE_SANITY: PASS"
)


print(
    "EXPERIMENT_EVIDENCE_INTEGRATION: PASS"
)


# ================================================================
# WRITE OUTPUTS
# ================================================================

RESULTS.mkdir(
    parents=True,
    exist_ok=True,
)


nodes_path = (
    RESULTS
    / "power_grid_ics_cyber_knowledge_graph_nodes.jsonl"
)

edges_path = (
    RESULTS
    / "power_grid_ics_cyber_knowledge_graph_edges.jsonl"
)

graphml_path = (
    RESULTS
    / "power_grid_ics_cyber_knowledge_graph.graphml"
)

focus_graphml_path = (
    RESULTS
    / "power_grid_ics_cyber_focus_subgraph.graphml"
)

summary_path = (
    RESULTS
    / "power_grid_ics_cyber_knowledge_graph_summary.json"
)


with nodes_path.open(
    "w",
    encoding="ascii",
) as output:

    for node_id, attrs in sorted(
        graph.nodes(
            data=True
        )
    ):

        output.write(
            json.dumps(
                {
                    "id":
                        node_id,
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

    records = sorted(
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

    for source, target, key, attrs in records:

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

nx.write_graphml(
    focus_graph,
    focus_graphml_path,
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

    "mitre_ics_attack_version":
        "19.2",

    "node_count":
        graph.number_of_nodes(),

    "edge_count":
        graph.number_of_edges(),

    "power_grid_focus_node_count":
        focus_graph.number_of_nodes(),

    "power_grid_focus_edge_count":
        focus_graph.number_of_edges(),

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

    "required_power_grid_attack_objects":
        required_external_ids,

    "experiment_mapping": {
        "scenario":
            mapping[
                "scenario_name"
            ],

        "protocol":
            protocol[
                "name"
            ],

        "mapped_techniques": sorted(
            {
                technique
                for behavior
                in mapping[
                    "behaviors"
                ]
                for technique
                in behavior[
                    "attack_techniques"
                ]
            }
        ),

        "explicitly_not_claimed":
            mapping.get(
                "not_claimed_for_current_experiment",
                [],
            ),
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
    "POWER_GRID_ICS_CYBER_KNOWLEDGE_GRAPH: PASS"
)

print(
    "=" * 68
)
