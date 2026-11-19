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
