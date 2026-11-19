#!/usr/bin/env bash

set -euo pipefail
set -o pipefail

SETUP="$HOME/ecpomdg_setup/power_grid_component_topology_knowledge_graph"
AUDIT="$HOME/ecpomdg_audit/power_grid_component_topology_knowledge_graph"

mkdir -p "$SETUP" "$AUDIT"

echo "================================================================"
echo " EC-POMDG POWER-GRID COMPONENT + TOPOLOGY KNOWLEDGE GRAPH"
echo "================================================================"


# ================================================================
# 1. DEFINE REPRODUCIBLE SPHERE TOPOLOGY
# ================================================================

echo
echo "===== DEFINE SPHERE TOPOLOGY MANIFEST ====="

cat > "$SETUP/sphere_cyber_physical_topology_manifest.json" <<'JSON'
{
  "schema_version": 1,
  "experiment": "powergridtestbed",
  "description": "EC-POMDG SPHERE cyber-physical topology",
  "network_segments": {
    "attack_access": "10.10.0.0/24",
    "supervisory": "10.20.0.0/24",
    "gateway_transit": "10.25.0.0/24",
    "field_control": "10.30.0.0/24",
    "physical_process": "10.40.0.0/24",
    "telemetry": "10.45.0.0/24",
    "defense": "10.50.0.0/24"
  },
  "assets": {
    "attacker": {
      "role": "attacker",
      "interfaces": ["10.10.0.10"]
    },
    "collector": {
      "role": "telemetry_collector",
      "interfaces": ["10.45.0.30", "10.50.0.20"]
    },
    "controller": {
      "role": "real_controller",
      "interfaces": ["10.30.0.10", "10.40.0.10"],
      "trusted_asset_id": "asset-field-001",
      "physical_grid_connected": true
    },
    "decoy": {
      "role": "decoy_controller",
      "interfaces": ["10.30.0.99"],
      "trusted_asset_id": "asset-field-002",
      "physical_grid_connected": false
    },
    "defender": {
      "role": "defender",
      "interfaces": ["10.50.0.40"]
    },
    "edgegw": {
      "role": "edge_gateway",
      "interfaces": [
        "10.10.0.1",
        "10.20.0.1",
        "10.25.0.1",
        "10.45.0.1"
      ]
    },
    "fieldgw": {
      "role": "field_gateway",
      "interfaces": [
        "10.25.0.2",
        "10.30.0.1",
        "10.45.0.20"
      ]
    },
    "gridsim": {
      "role": "physical_grid_simulator",
      "interfaces": ["10.40.0.20"]
    },
    "historian": {
      "role": "historian",
      "interfaces": ["10.20.0.20"]
    },
    "kg": {
      "role": "knowledge_graph_service",
      "interfaces": ["10.50.0.30"]
    },
    "operator": {
      "role": "human_operator",
      "interfaces": ["10.50.0.50"]
    },
    "scada": {
      "role": "scada_master",
      "interfaces": ["10.20.0.10", "10.45.0.10"]
    }
  },
  "services": [
    {
      "id": "real-iec104",
      "asset": "controller",
      "protocol": "IEC-60870-5-104",
      "endpoint": "10.30.0.10:2404"
    },
    {
      "id": "decoy-iec104",
      "asset": "decoy",
      "protocol": "IEC-60870-5-104",
      "endpoint": "10.30.0.99:2404"
    },
    {
      "id": "physical-plant-api",
      "asset": "gridsim",
      "protocol": "HTTP",
      "endpoint": "10.40.0.20:8765"
    },
    {
      "id": "telemetry-ingress",
      "asset": "collector",
      "protocol": "HTTP",
      "endpoint": "10.45.0.30:9201"
    },
    {
      "id": "defender-observation-api",
      "asset": "collector",
      "protocol": "HTTP",
      "endpoint": "10.50.0.20:9202"
    }
  ],
  "relationships": [
    {
      "source": "scada",
      "target": "controller",
      "relation": "communicates_with",
      "protocol": "IEC-60870-5-104"
    },
    {
      "source": "scada",
      "target": "decoy",
      "relation": "communicates_with",
      "protocol": "IEC-60870-5-104"
    },
    {
      "source": "attacker",
      "target": "controller",
      "relation": "experiment_attack_path",
      "protocol": "IEC-60870-5-104"
    },
    {
      "source": "attacker",
      "target": "decoy",
      "relation": "experiment_attack_path",
      "protocol": "IEC-60870-5-104"
    },
    {
      "source": "controller",
      "target": "gridsim",
      "relation": "controls_physical_process",
      "protocol": "HTTP"
    },
    {
      "source": "controller",
      "target": "collector",
      "relation": "publishes_telemetry",
      "protocol": "HTTP"
    },
    {
      "source": "decoy",
      "target": "collector",
      "relation": "publishes_telemetry",
      "protocol": "HTTP"
    },
    {
      "source": "collector",
      "target": "defender",
      "relation": "provides_operational_observations",
      "protocol": "HTTP"
    },
    {
      "source": "kg",
      "target": "defender",
      "relation": "provides_knowledge_context",
      "protocol": "KG"
    }
  ]
}
JSON

python3 -m json.tool \
  "$SETUP/sphere_cyber_physical_topology_manifest.json" \
  >/dev/null

echo "SPHERE_TOPOLOGY_MANIFEST_SYNTAX: PASS"


# ================================================================
# 2. LIVE SPHERE INTERFACE VALIDATION
# ================================================================

echo
echo "===== CREATE LIVE SPHERE INTERFACE VALIDATOR ====="

cat > "$SETUP/validate_sphere_topology_manifest.py" <<'PY'
#!/usr/bin/env python3

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


manifest_path = Path(
    sys.argv[1]
)

output_path = Path(
    sys.argv[2]
)

manifest = json.loads(
    manifest_path.read_text(
        encoding="utf-8"
    )
)

results = {
    "validated_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),
    "assets": {},
}

failed = []


for asset, config in manifest["assets"].items():

    completed = subprocess.run(
        [
            "ssh",
            asset,
            "ip -4 -o addr show",
        ],
        text=True,
        capture_output=True,
        timeout=15,
    )

    if completed.returncode != 0:

        failed.append(
            f"{asset}: ssh/ip command failed"
        )

        results["assets"][asset] = {
            "ok": False,
            "stderr":
                completed.stderr.strip(),
        }

        continue

    observed = sorted(
        set(
            re.findall(
                r"\binet\s+"
                r"([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)"
                r"/",
                completed.stdout,
            )
        )
    )

    expected = sorted(
        config["interfaces"]
    )

    missing = [
        ip
        for ip in expected
        if ip not in observed
    ]

    ok = not missing

    if not ok:

        failed.append(
            f"{asset}: missing {missing}"
        )

    results["assets"][asset] = {
        "ok":
            ok,
        "expected_experiment_ips":
            expected,
        "observed_ipv4":
            observed,
        "missing":
            missing,
    }


output_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

output_path.write_text(
    json.dumps(
        results,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


for asset, result in results["assets"].items():

    status = (
        "PASS"
        if result["ok"]
        else "FAIL"
    )

    print(
        asset,
        status,
        result.get(
            "expected_experiment_ips",
            [],
        ),
    )


if failed:

    raise SystemExit(
        "SPHERE topology mismatch: "
        + "; ".join(failed)
    )


print()
print(
    "SPHERE_LIVE_INTERFACE_VALIDATION: PASS"
)
PY


python3 -m py_compile \
  "$SETUP/validate_sphere_topology_manifest.py"


python3 \
  "$SETUP/validate_sphere_topology_manifest.py" \
  "$SETUP/sphere_cyber_physical_topology_manifest.json" \
  "$AUDIT/sphere_live_interface_validation.json"


# ================================================================
# 3. CAPTURE ACTUAL OPENDSS PHYSICAL TOPOLOGY
# ================================================================

echo
echo "===== CREATE OPENDSS TOPOLOGY CAPTURE ====="

cat > "$SETUP/capture_ieee13_physical_topology.py" <<'PY'
#!/usr/bin/env python3

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import opendssdirect as dss


MODEL_ROOT = (
    Path.home()
    / "ecpomdg"
    / "t2_gridsim"
    / "models"
    / "ieee13"
)

BASE_DSS = (
    MODEL_ROOT
    / "IEEE13Nodeckt.dss"
)

LINECODES = (
    MODEL_ROOT
    / "IEEELineCodes.dss"
)

BUSXY = (
    MODEL_ROOT
    / "IEEE13Node_BusXY.csv"
)

DER_EXTENSION = (
    MODEL_ROOT
    / "extensions"
    / "ecpomdg_der.dss"
)

OUTPUT = (
    Path.home()
    / "ecpomdg"
    / "power_grid_component_topology"
    / "source"
    / "ieee13_physical_topology_snapshot.json"
)


def sha256(path):

    digest = hashlib.sha256()

    with path.open("rb") as handle:

        for block in iter(
            lambda:
                handle.read(
                    1024 * 1024
                ),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def normalize_bus(bus):

    if not bus:
        return ""

    return (
        bus.split(".")[0]
        .strip()
        .lower()
    )


for path in (
    BASE_DSS,
    LINECODES,
    BUSXY,
    DER_EXTENSION,
):

    if not path.exists():

        raise SystemExit(
            f"Missing physical model source: {path}"
        )


os.chdir(
    MODEL_ROOT
)

dss.Basic.ClearAll()

dss.Text.Command(
    f'Redirect "{BASE_DSS}"'
)

dss.Text.Command(
    f'Redirect "{DER_EXTENSION}"'
)

dss.Solution.Solve()

assert dss.Solution.Converged()


buses = sorted(
    {
        str(bus).lower()
        for bus
        in dss.Circuit.AllBusNames()
    }
)


elements = []

class_counts = Counter()


for full_name in dss.Circuit.AllElementNames():

    dss.Circuit.SetActiveElement(
        full_name
    )

    buses_for_element = [
        normalize_bus(bus)
        for bus
        in dss.CktElement.BusNames()
        if normalize_bus(bus)
    ]

    element_class, _, element_name = (
        full_name.partition(".")
    )

    element_class = (
        element_class.lower()
    )

    class_counts[
        element_class
    ] += 1

    elements.append({
        "full_name":
            full_name,
        "class":
            element_class,
        "name":
            element_name,
        "buses":
            buses_for_element,
        "enabled":
            bool(
                dss.CktElement.Enabled()
            ),
    })


snapshot = {
    "captured_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "model":
        "IEEE 13 Node Test Feeder",

    "converged":
        bool(
            dss.Solution.Converged()
        ),

    "buses":
        buses,

    "elements":
        elements,

    "class_counts":
        dict(
            sorted(
                class_counts.items()
            )
        ),

    "source_files": {
        "IEEE13Nodeckt.dss": {
            "sha256":
                sha256(
                    BASE_DSS
                )
        },
        "IEEELineCodes.dss": {
            "sha256":
                sha256(
                    LINECODES
                )
        },
        "IEEE13Node_BusXY.csv": {
            "sha256":
                sha256(
                    BUSXY
                )
        },
        "extensions/ecpomdg_der.dss": {
            "sha256":
                sha256(
                    DER_EXTENSION
                )
        }
    }
}


assert len(buses) == 16, len(buses)

assert class_counts[
    "line"
] == 12, class_counts

assert class_counts[
    "load"
] == 15, class_counts

assert class_counts.get(
    "pvsystem",
    0,
) >= 1, class_counts

assert "675" in buses


pv_at_675 = False

for element in elements:

    if (
        element["class"]
        == "pvsystem"
        and "675"
        in element["buses"]
    ):

        pv_at_675 = True


assert pv_at_675


OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT.write_text(
    json.dumps(
        snapshot,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="ascii",
)


print(
    "OpenDSS converged:",
    snapshot["converged"],
)

print(
    "buses:",
    len(buses),
)

print(
    "lines:",
    class_counts["line"],
)

print(
    "loads:",
    class_counts["load"],
)

print(
    "PVSystems:",
    class_counts["pvsystem"],
)

print(
    "PVSystem connected to bus 675:",
    pv_at_675,
)

print()
print(
    "IEEE13_PHYSICAL_TOPOLOGY_CAPTURE: PASS"
)

print(
    "Snapshot:",
    OUTPUT,
)
PY


python3 -m py_compile \
  "$SETUP/capture_ieee13_physical_topology.py"


echo
echo "===== DEPLOY PHYSICAL TOPOLOGY CAPTURE TO GRIDSIM ====="

ssh gridsim '
mkdir -p \
  ~/ecpomdg/power_grid_component_topology/app \
  ~/ecpomdg/power_grid_component_topology/source
'


# FIX: the original OpenDSS venv on gridsim was lost with the plant, so the live
# re-capture can't run. Use the frozen IEEE-13 snapshot instead (the real
# original capture); stage it from the backup if it isn't already in AUDIT.
AUD_SNAP="$AUDIT/ieee13_physical_topology_snapshot.json"
mkdir -p "$AUDIT"
if [ ! -f "$AUD_SNAP" ]; then
  for b in "${BACKUP_DIR:-$HOME/backup_dir}" "$HOME/backup/backup_dir"; do
    cand="$b/ecpomdg_audit/power_grid_component_topology_knowledge_graph/ieee13_physical_topology_snapshot.json"
    [ -f "$cand" ] && { cp "$cand" "$AUD_SNAP"; break; }
  done
fi

if [ -f "$AUD_SNAP" ]; then
  echo "FROZEN_IEEE13_SNAPSHOT: using existing snapshot (OpenDSS re-capture skipped)"
else
  echo "No frozen snapshot found; attempting live OpenDSS capture on gridsim"
  scp \
    "$SETUP/capture_ieee13_physical_topology.py" \
    gridsim:~/ecpomdg/power_grid_component_topology/app/
  ssh gridsim '
  set -euo pipefail
  VENV="$HOME/ecpomdg/venvs/gridsim"
  "$VENV/bin/python" \
    ~/ecpomdg/power_grid_component_topology/app/capture_ieee13_physical_topology.py
  '
  scp \
    gridsim:~/ecpomdg/power_grid_component_topology/source/ieee13_physical_topology_snapshot.json \
    "$AUDIT/"
fi


# ================================================================
# 4. PREPARE KG NODE INPUTS
# ================================================================

echo
echo "===== PREPARE KG NODE INPUTS ====="

ssh kg '
mkdir -p \
  ~/ecpomdg/knowledge_graphs/power_grid_component_topology/app \
  ~/ecpomdg/knowledge_graphs/power_grid_component_topology/source \
  ~/ecpomdg/knowledge_graphs/power_grid_component_topology/results \
  ~/ecpomdg/knowledge_graphs/power_grid_component_topology/audit
'


scp \
  "$SETUP/sphere_cyber_physical_topology_manifest.json" \
  kg:~/ecpomdg/knowledge_graphs/power_grid_component_topology/source/

scp \
  "$AUDIT/sphere_live_interface_validation.json" \
  kg:~/ecpomdg/knowledge_graphs/power_grid_component_topology/source/

scp \
  "$AUDIT/ieee13_physical_topology_snapshot.json" \
  kg:~/ecpomdg/knowledge_graphs/power_grid_component_topology/source/


# Trusted operational asset registry.
test -f \
  "$HOME/ecpomdg_setup/telemetry_ground_truth/defender_trusted_asset_registry.json"

scp \
  "$HOME/ecpomdg_setup/telemetry_ground_truth/defender_trusted_asset_registry.json" \
  kg:~/ecpomdg/knowledge_graphs/power_grid_component_topology/source/


# ================================================================
# 5. BUILD COMPONENT + TOPOLOGY KG
# ================================================================

echo
echo "===== CREATE COMPONENT + TOPOLOGY KG BUILDER ====="

cat > "$SETUP/build_power_grid_component_topology_knowledge_graph.py" <<'PY'
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
PY


python3 -m py_compile \
  "$SETUP/build_power_grid_component_topology_knowledge_graph.py"

echo \
  "COMPONENT_TOPOLOGY_KG_BUILDER_SYNTAX: PASS"


scp \
  "$SETUP/build_power_grid_component_topology_knowledge_graph.py" \
  kg:~/ecpomdg/knowledge_graphs/power_grid_component_topology/app/


# ================================================================
# 6. BUILD
# ================================================================

echo
echo "===== BUILD COMPONENT + TOPOLOGY KG ====="

ssh kg '
set -euo pipefail

BASE="$HOME/ecpomdg/knowledge_graphs/power_grid_component_topology"
VENV="$HOME/ecpomdg/venvs/knowledge_graphs"

PYTHONIOENCODING=UTF-8 \
"$VENV/bin/python" \
  "$BASE/app/build_power_grid_component_topology_knowledge_graph.py" \
  | tee \
  "$BASE/results/power_grid_component_topology_knowledge_graph_build.log"
'


# ================================================================
# 7. INDEPENDENT VALIDATION
# ================================================================

echo
echo "===== INDEPENDENT RESULT VALIDATION ====="

ssh kg python3 - <<'PY'
import json
from pathlib import Path

path = (
    Path.home()
    / "ecpomdg"
    / "knowledge_graphs"
    / "power_grid_component_topology"
    / "results"
    / "power_grid_component_topology_knowledge_graph_summary.json"
)

summary = json.loads(
    path.read_text(
        encoding="ascii"
    )
)

print(
    "nodes:",
    summary["node_count"]
)

print(
    "edges:",
    summary["edge_count"]
)

print(
    "SPHERE assets:",
    summary["sphere_assets"]
)

print(
    "network segments:",
    summary["network_segments"]
)

print(
    "grid buses:",
    summary["grid_buses"]
)

print(
    "smart inverter:",
    summary["smart_inverter_nodes"]
)


assert summary[
    "sphere_assets"
] == 12

assert summary[
    "network_segments"
] == 7

assert summary[
    "grid_buses"
] == 16

assert summary[
    "grid_component_classes"
][
    "line"
] == 12

assert summary[
    "grid_component_classes"
][
    "load"
] == 15

assert summary[
    "cyber_physical_bridge"
][
    "real_controller"
] is True

assert summary[
    "cyber_physical_bridge"
][
    "decoy_controller"
] is False

assert (
    summary[
        "trusted_asset_mapping"
    ][
        "controller"
    ]
    == "asset-field-001"
)

assert (
    summary[
        "trusted_asset_mapping"
    ][
        "decoy"
    ]
    == "asset-field-002"
)


print(
    "COMPONENT_TOPOLOGY_SUMMARY_VALIDATION: PASS"
)

print(
    "CYBER_PHYSICAL_BRIDGE_VALIDATION: PASS"
)

print(
    "POWER_GRID_COMPONENT_TOPOLOGY_INDEPENDENT_VALIDATION: PASS"
)
PY


# ================================================================
# 8. FREEZE
# ================================================================

echo
echo "===== FREEZE COMPONENT + TOPOLOGY KG ====="

ssh kg '
set -euo pipefail

BASE="$HOME/ecpomdg/knowledge_graphs/power_grid_component_topology"

sha256sum \
  "$BASE/source/sphere_cyber_physical_topology_manifest.json" \
  "$BASE/source/sphere_live_interface_validation.json" \
  "$BASE/source/ieee13_physical_topology_snapshot.json" \
  "$BASE/source/defender_trusted_asset_registry.json" \
  "$BASE/app/build_power_grid_component_topology_knowledge_graph.py" \
  "$BASE/results/power_grid_component_topology_knowledge_graph_nodes.jsonl" \
  "$BASE/results/power_grid_component_topology_knowledge_graph_edges.jsonl" \
  "$BASE/results/power_grid_component_topology_knowledge_graph.graphml" \
  "$BASE/results/power_grid_component_topology_knowledge_graph_summary.json" \
  "$BASE/results/power_grid_component_topology_knowledge_graph_build.log" \
  > \
  "$BASE/audit/power_grid_component_topology_knowledge_graph_sha256.txt"

cat \
  "$BASE/audit/power_grid_component_topology_knowledge_graph_sha256.txt"
'


# ================================================================
# 9. COPY AUDIT OUTPUTS
# ================================================================

echo
echo "===== COPY AUDIT OUTPUTS ====="

scp \
  kg:~/ecpomdg/knowledge_graphs/power_grid_component_topology/results/power_grid_component_topology_knowledge_graph_summary.json \
  "$AUDIT/"

scp \
  kg:~/ecpomdg/knowledge_graphs/power_grid_component_topology/results/power_grid_component_topology_knowledge_graph_build.log \
  "$AUDIT/"

scp \
  kg:~/ecpomdg/knowledge_graphs/power_grid_component_topology/audit/power_grid_component_topology_knowledge_graph_sha256.txt \
  "$AUDIT/"


echo
echo "================================================================"
echo "POWER_GRID_COMPONENT_TOPOLOGY_KNOWLEDGE_GRAPH_BUILD: PASS"
echo "================================================================"

