#!/usr/bin/env python3

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import networkx as nx


BASE = (
    Path.home()
    / "ecpomdg"
    / "knowledge_graphs"
    / "general_cyber"
)

SOURCE = BASE / "source"
RESULTS = BASE / "results"

ATTACK_PATH = (
    SOURCE
    / "mitre_enterprise_attack_v19_2.json"
)

CAPEC_PATH = (
    SOURCE
    / "capec_v3_9.xml"
)

CWE_PATH = (
    SOURCE
    / "cwe_v4_20.xml"
)

KEV_PATH = (
    SOURCE
    / "cisa_known_exploited_vulnerabilities.json"
)

NODES_PATH = (
    RESULTS
    / "general_cyber_knowledge_graph_nodes.jsonl"
)

EDGES_PATH = (
    RESULTS
    / "general_cyber_knowledge_graph_edges.jsonl"
)

GRAPHML_PATH = (
    RESULTS
    / "general_cyber_knowledge_graph.graphml"
)

SUMMARY_PATH = (
    RESULTS
    / "general_cyber_knowledge_graph_summary.json"
)


graph = nx.MultiDiGraph(
    name="EC-POMDG General Cyber Knowledge Graph"
)


# ================================================================
# Helpers
# ================================================================

def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def normalized_text(value):
    if value is None:
        return ""

    return " ".join(
        str(value).split()
    )


def slug(value):
    value = normalized_text(value).lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    )

    return value.strip("-") or "unknown"


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
    node_id,
    **attrs,
):
    cleaned = {
        key: scalar(value)
        for key, value
        in attrs.items()
    }

    if graph.has_node(
        node_id
    ):
        graph.nodes[
            node_id
        ].update(
            {
                k: v
                for k, v
                in cleaned.items()
                if v not in ("", None)
            }
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
    if not graph.has_node(source):
        return

    if not graph.has_node(target):
        return

    graph.add_edge(
        source,
        target,
        relation=relation,
        source_dataset=source_dataset,
        **{
            key:
                scalar(value)
            for key, value
            in attrs.items()
        },
    )


def find_external_id(
    obj,
):
    for ref in obj.get(
        "external_references",
        [],
    ):
        external_id = (
            ref.get(
                "external_id"
            )
        )

        if external_id:
            return external_id

    return ""


# ================================================================
# MITRE ENTERPRISE ATT&CK
# ================================================================

print(
    "===== MITRE ENTERPRISE ATT&CK ====="
)

attack = json.loads(
    ATTACK_PATH.read_text(
        encoding="utf-8"
    )
)

objects = attack[
    "objects"
]

attack_external_lookup = {}
attack_objects = {}

supported_types = {
    "attack-pattern",
    "campaign",
    "course-of-action",
    "intrusion-set",
    "malware",
    "tool",
    "x-mitre-data-component",
    "x-mitre-data-source",
    "x-mitre-tactic",
}

for obj in objects:

    object_type = obj.get(
        "type"
    )

    if (
        object_type
        not in supported_types
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
        "ATTACK::"
        + stix_id
    )

    external_id = (
        find_external_id(
            obj
        )
    )

    add_node(
        node_id,
        node_type=
            "attack_"
            + object_type.replace(
                "-",
                "_",
            ),
        source_dataset=
            "MITRE Enterprise ATT&CK 19.2",
        external_id=
            external_id,
        name=
            obj.get(
                "name",
                "",
            ),
        description=
            normalized_text(
                obj.get(
                    "description",
                    ""
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
    )

    attack_objects[
        stix_id
    ] = node_id

    if external_id:

        attack_external_lookup[
            external_id
        ] = node_id


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

    source_ref = obj.get(
        "source_ref"
    )

    target_ref = obj.get(
        "target_ref"
    )

    if (
        source_ref
        not in attack_objects
        or target_ref
        not in attack_objects
    ):
        continue

    add_edge(
        attack_objects[
            source_ref
        ],
        attack_objects[
            target_ref
        ],
        relation=
            obj.get(
                "relationship_type",
                "related_to",
            ),
        source_dataset=
            "MITRE Enterprise ATT&CK 19.2",
        description=
            normalized_text(
                obj.get(
                    "description",
                    ""
                )
            ),
    )


# Technique -> tactic relationships.
tactic_shortname_lookup = {}

for obj in objects:

    if obj.get(
        "type"
    ) != "x-mitre-tactic":
        continue

    if obj[
        "id"
    ] not in attack_objects:
        continue

    shortname = obj.get(
        "x_mitre_shortname"
    )

    if shortname:

        tactic_shortname_lookup[
            shortname
        ] = attack_objects[
            obj["id"]
        ]


for obj in objects:

    if obj.get(
        "type"
    ) != "attack-pattern":
        continue

    if obj[
        "id"
    ] not in attack_objects:
        continue

    technique_node = (
        attack_objects[
            obj["id"]
        ]
    )

    for phase in obj.get(
        "kill_chain_phases",
        [],
    ):

        phase_name = phase.get(
            "phase_name"
        )

        tactic_node = (
            tactic_shortname_lookup.get(
                phase_name
            )
        )

        if tactic_node:

            add_edge(
                technique_node,
                tactic_node,
                relation=
                    "belongs_to_tactic",
                source_dataset=
                    "MITRE Enterprise ATT&CK 19.2",
            )


print(
    "ATT&CK nodes:",
    len(attack_objects),
)


# ================================================================
# CWE
# ================================================================

print()
print(
    "===== CWE ====="
)

cwe_root = ET.parse(
    CWE_PATH
).getroot()

cwe_nodes = {}

for element in cwe_root.iter():

    if local_name(
        element.tag
    ) != "Weakness":
        continue

    # The full MITRE XML preserves deprecated weakness entries.
    # The official CWE 4.20 total (944) counts active weaknesses.
    if (
        element.attrib.get(
            "Status",
            "",
        )
        .strip()
        .lower()
        == "deprecated"
    ):
        continue

    cwe_id = element.attrib.get(
        "ID"
    )

    if not cwe_id:
        continue

    node_id = (
        f"CWE::{cwe_id}"
    )

    add_node(
        node_id,
        node_type=
            "cwe_weakness",
        source_dataset=
            "CWE 4.20",
        external_id=
            f"CWE-{cwe_id}",
        name=
            element.attrib.get(
                "Name",
                "",
            ),
        abstraction=
            element.attrib.get(
                "Abstraction",
                "",
            ),
        structure=
            element.attrib.get(
                "Structure",
                "",
            ),
        status=
            element.attrib.get(
                "Status",
                "",
            ),
    )

    cwe_nodes[
        cwe_id
    ] = node_id


# CWE hierarchy.
for element in cwe_root.iter():

    if local_name(
        element.tag
    ) != "Weakness":
        continue

    source_id = element.attrib.get(
        "ID"
    )

    if (
        not source_id
        or source_id
        not in cwe_nodes
    ):
        continue

    for child in element.iter():

        if local_name(
            child.tag
        ) != "Related_Weakness":
            continue

        target_id = (
            child.attrib.get(
                "CWE_ID"
            )
        )

        nature = (
            child.attrib.get(
                "Nature",
                "RelatedTo",
            )
        )

        if target_id in cwe_nodes:

            add_edge(
                cwe_nodes[
                    source_id
                ],
                cwe_nodes[
                    target_id
                ],
                relation=
                    "cwe_"
                    + slug(
                        nature
                    ),
                source_dataset=
                    "CWE 4.20",
                view_id=
                    child.attrib.get(
                        "View_ID",
                        "",
                    ),
            )


print(
    "CWE weaknesses:",
    len(cwe_nodes),
)


# ================================================================
# CAPEC
# ================================================================

print()
print(
    "===== CAPEC ====="
)

capec_root = ET.parse(
    CAPEC_PATH
).getroot()

capec_nodes = {}

attack_patterns = [
    element
    for element in capec_root.iter()
    if local_name(
        element.tag
    ) == "Attack_Pattern"
]

for pattern in attack_patterns:

    # The full MITRE XML preserves deprecated attack patterns.
    # The official CAPEC 3.9 total (559) counts active patterns.
    if (
        pattern.attrib.get(
            "Status",
            "",
        )
        .strip()
        .lower()
        == "deprecated"
    ):
        continue

    capec_id = pattern.attrib.get(
        "ID"
    )

    if not capec_id:
        continue

    node_id = (
        f"CAPEC::{capec_id}"
    )

    add_node(
        node_id,
        node_type=
            "capec_attack_pattern",
        source_dataset=
            "CAPEC 3.9",
        external_id=
            f"CAPEC-{capec_id}",
        name=
            pattern.attrib.get(
                "Name",
                "",
            ),
        abstraction=
            pattern.attrib.get(
                "Abstraction",
                "",
            ),
        status=
            pattern.attrib.get(
                "Status",
                "",
            ),
    )

    capec_nodes[
        capec_id
    ] = node_id


for pattern in attack_patterns:

    source_id = pattern.attrib.get(
        "ID"
    )

    if source_id not in capec_nodes:
        continue

    source_node = (
        capec_nodes[
            source_id
        ]
    )

    # CAPEC -> CAPEC relationships.
    for child in pattern.iter():

        if local_name(
            child.tag
        ) != "Related_Attack_Pattern":
            continue

        target_id = child.attrib.get(
            "CAPEC_ID"
        )

        if target_id not in capec_nodes:
            continue

        nature = child.attrib.get(
            "Nature",
            "RelatedTo",
        )

        add_edge(
            source_node,
            capec_nodes[
                target_id
            ],
            relation=
                "capec_"
                + slug(
                    nature
                ),
            source_dataset=
                "CAPEC 3.9",
        )

    # CAPEC -> CWE.
    for child in pattern.iter():

        if local_name(
            child.tag
        ) != "Related_Weakness":
            continue

        weakness_id = child.attrib.get(
            "CWE_ID"
        )

        if weakness_id in cwe_nodes:

            add_edge(
                source_node,
                cwe_nodes[
                    weakness_id
                ],
                relation=
                    "related_weakness",
                source_dataset=
                    "CAPEC 3.9",
            )

    # CAPEC -> ATT&CK mappings where provided by CAPEC.
    for mapping in pattern.iter():

        if local_name(
            mapping.tag
        ) != "Taxonomy_Mapping":
            continue

        taxonomy = (
            mapping.attrib.get(
                "Taxonomy_Name",
                ""
            )
            .upper()
        )

        if (
            "ATTACK"
            not in taxonomy
            and "ATT&CK"
            not in taxonomy
        ):
            continue

        entry_id = ""

        for item in mapping.iter():

            if local_name(
                item.tag
            ) == "Entry_ID":

                entry_id = normalized_text(
                    item.text
                )

                break

        if (
            entry_id
            and entry_id
            in attack_external_lookup
        ):

            add_edge(
                source_node,
                attack_external_lookup[
                    entry_id
                ],
                relation=
                    "mapped_to_attack_technique",
                source_dataset=
                    "CAPEC 3.9",
            )


print(
    "CAPEC attack patterns:",
    len(capec_nodes),
)


# ================================================================
# CISA KNOWN EXPLOITED VULNERABILITIES
# ================================================================

print()
print(
    "===== CISA KEV ====="
)

kev = json.loads(
    KEV_PATH.read_text(
        encoding="utf-8"
    )
)

catalog_node = (
    "DATASET::CISA_KEV"
)

add_node(
    catalog_node,
    node_type=
        "vulnerability_catalog",
    source_dataset=
        "CISA KEV",
    external_id=
        "CISA-KEV",
    name=
        "CISA Known Exploited Vulnerabilities",
    catalog_version=
        kev.get(
            "catalogVersion",
            "",
        ),
    date_released=
        kev.get(
            "dateReleased",
            "",
        ),
)


kev_cve_nodes = set()

for item in kev.get(
    "vulnerabilities",
    [],
):

    cve = item.get(
        "cveID"
    )

    if not cve:
        continue

    cve_node = (
        "CVE::"
        + cve
    )

    kev_cve_nodes.add(
        cve_node
    )

    add_node(
        cve_node,
        node_type=
            "cve",
        source_dataset=
            "CISA KEV",
        external_id=
            cve,
        name=
            item.get(
                "vulnerabilityName",
                cve,
            ),
        date_added=
            item.get(
                "dateAdded",
                "",
            ),
        due_date=
            item.get(
                "dueDate",
                "",
            ),
        short_description=
            normalized_text(
                item.get(
                    "shortDescription",
                    "",
                )
            ),
        required_action=
            normalized_text(
                item.get(
                    "requiredAction",
                    "",
                )
            ),
        ransomware_use=
            item.get(
                "knownRansomwareCampaignUse",
                "",
            ),
    )

    add_edge(
        cve_node,
        catalog_node,
        relation=
            "listed_in",
        source_dataset=
            "CISA KEV",
    )

    vendor = item.get(
        "vendorProject",
        "Unknown",
    )

    product = item.get(
        "product",
        "Unknown",
    )

    vendor_node = (
        "VENDOR::"
        + slug(vendor)
    )

    product_node = (
        "PRODUCT::"
        + slug(vendor)
        + "::"
        + slug(product)
    )

    add_node(
        vendor_node,
        node_type=
            "vendor",
        source_dataset=
            "CISA KEV",
        name=
            vendor,
    )

    add_node(
        product_node,
        node_type=
            "product",
        source_dataset=
            "CISA KEV",
        name=
            product,
        vendor=
            vendor,
    )

    add_edge(
        vendor_node,
        product_node,
        relation=
            "supplies",
        source_dataset=
            "CISA KEV",
    )

    add_edge(
        cve_node,
        product_node,
        relation=
            "affects",
        source_dataset=
            "CISA KEV",
    )

    for cwe in item.get(
        "cwes",
        [],
    ):

        match = re.fullmatch(
            r"CWE-(\d+)",
            str(cwe),
        )

        if not match:
            continue

        cwe_id = match.group(
            1
        )

        cwe_node = (
            cwe_nodes.get(
                cwe_id
            )
        )

        if cwe_node:

            add_edge(
                cve_node,
                cwe_node,
                relation=
                    "has_weakness",
                source_dataset=
                    "CISA KEV",
            )


print(
    "CISA KEV CVEs:",
    len(
        kev_cve_nodes
    ),
)


# ================================================================
# OUTPUT
# ================================================================

print()
print(
    "===== WRITE GRAPH ====="
)

RESULTS.mkdir(
    parents=True,
    exist_ok=True,
)


with NODES_PATH.open(
    "w",
    encoding="ascii",
) as output:

    for node_id, attrs in sorted(
        graph.nodes(
            data=True
        )
    ):

        record = {
            "id":
                node_id,
            **attrs,
        }

        output.write(
            json.dumps(
                record,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        )


with EDGES_PATH.open(
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

        record = {
            "source":
                source,
            "target":
                target,
            "edge_key":
                key,
            **attrs,
        }

        output.write(
            json.dumps(
                record,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        )


nx.write_graphml(
    graph,
    GRAPHML_PATH,
)


node_counts = Counter(
    attrs.get(
        "node_type",
        "unknown",
    )
    for _, attrs
    in graph.nodes(
        data=True
    )
)

edge_counts = Counter(
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
                node_counts.items()
            )
        ),

    "edge_relations":
        dict(
            sorted(
                edge_counts.items()
            )
        ),

    "source_versions": {
        "mitre_enterprise_attack":
            "19.2",

        "capec":
            "3.9",

        "cwe":
            "4.20",

        "cisa_kev_catalog_version":
            kev.get(
                "catalogVersion",
                "",
            ),

        "cisa_kev_date_released":
            kev.get(
                "dateReleased",
                "",
            ),
    },
}


SUMMARY_PATH.write_text(
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
    "===== VALIDATION ====="
)


# ATT&CK sanity.
attack_techniques = [
    attrs
    for _, attrs
    in graph.nodes(
        data=True
    )
    if (
        attrs.get(
            "node_type"
        )
        == "attack_attack_pattern"
    )
]

assert (
    len(
        attack_techniques
    )
    > 500
), len(
    attack_techniques
)

assert (
    "T1059"
    in attack_external_lookup
)

print(
    "MITRE_ATTACK_INGESTION: PASS"
)


# Current CAPEC 3.9 contains 559 attack patterns.
assert (
    len(
        capec_nodes
    )
    == 559
), len(
    capec_nodes
)

print(
    "CAPEC_INGESTION: PASS"
)


# CWE 4.20 contains 944 weakness entries.
assert (
    len(
        cwe_nodes
    )
    == 944
), len(
    cwe_nodes
)

assert (
    "79"
    in cwe_nodes
)

print(
    "CWE_INGESTION: PASS"
)


# KEV is dynamic, so avoid hard-coding an exact catalog size.
assert (
    len(
        kev_cve_nodes
    )
    > 500
), len(
    kev_cve_nodes
)

assert graph.has_node(
    "CVE::CVE-2021-44228"
)

print(
    "CISA_KEV_INGESTION: PASS"
)


assert (
    graph.number_of_nodes()
    > 2500
)

assert (
    graph.number_of_edges()
    > 2000
)

print(
    "GRAPH_SCALE_SANITY: PASS"
)


# Verify cross-source attack-pattern -> weakness integration.
capec_cwe_edges = sum(
    1
    for _, _, attrs
    in graph.edges(
        data=True
    )
    if (
        attrs.get(
            "relation"
        )
        == "related_weakness"
    )
)

assert (
    capec_cwe_edges
    > 0
)

print(
    "CAPEC_CWE_LINKAGE: PASS"
)


# Verify CVE -> CWE integration where CISA provides CWE metadata.
kev_cwe_edges = sum(
    1
    for _, _, attrs
    in graph.edges(
        data=True
    )
    if (
        attrs.get(
            "relation"
        )
        == "has_weakness"
    )
)

assert (
    kev_cwe_edges
    > 0
)

print(
    "KEV_CWE_LINKAGE: PASS"
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
    "GENERAL_CYBER_KNOWLEDGE_GRAPH: PASS"
)

print(
    "=" * 68
)
