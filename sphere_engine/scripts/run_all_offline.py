#!/usr/bin/env python3
"""Reproduce the full offline result set (H2, H1, joint) end to end.

    python3 scripts/run_all_offline.py

Writes results/*.json and refreshes the provenance manifest. The offline
simulator is for ablation and pipeline validation; paper-grade numbers come
from matched SPHERE runs using the same src/ inference and policy code.
"""
from __future__ import annotations
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str, argv: list[str]) -> None:
    print(f"\n===== {script} {' '.join(argv)} =====", flush=True)
    sys.argv = [script, *argv]
    runpy.run_path(str(ROOT / "scripts" / script), run_name="__main__")


if __name__ == "__main__":
    run("run_offline_smoke.py", [])
    run("run_experiment_h2.py", ["--episodes", "400"])
    run("run_experiment_h1.py", ["--episodes", "500", "--val", "150"])
    run("run_experiment_joint.py", ["--episodes", "400", "--val", "150"])
    run("run_experiment_replay.py", ["--attack-actors", "160", "--benign-actors", "160", "--recurrence", "0.6"])
    print("\nALL_OFFLINE_EXPERIMENTS: DONE")
