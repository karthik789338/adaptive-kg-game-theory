#!/usr/bin/env python3
from __future__ import annotations
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Required for the offline experiments; neo4j is only needed for the SPHERE tier.
required = ["numpy", "pandas", "networkx"]
optional = ["neo4j"]
status = {}
for name in required + optional:
    try:
        mod = importlib.import_module(name)
        status[name] = getattr(mod, "__version__", "installed")
    except Exception as exc:
        status[name] = f"MISSING: {exc}"

from ecpomdg_final.provenance import manifest

print("EC-POMDG FINAL PREFLIGHT")
print(json.dumps({"dependencies": status, "project_files": len(manifest(ROOT)["files"])}, indent=2))
missing_required = [n for n in required if str(status[n]).startswith("MISSING")]
if missing_required:
    raise SystemExit(f"PREFLIGHT FAIL: missing required dependencies {missing_required}")
if str(status["neo4j"]).startswith("MISSING"):
    print("PREFLIGHT: PASS (offline; neo4j not installed -- required only for SPHERE Neo4j tier)")
else:
    print("PREFLIGHT: PASS")
