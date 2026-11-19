#!/usr/bin/env python3
"""Experiment 1 (H1 live): run live episodes across policies and aggregate.

Runs sphere/h1_live_episode.py on the testbed for each
  policy in {MONITOR_ONLY, FIXED_SCHEDULE, STAGE_AGNOSTIC, BELIEF_ADAPTIVE}
  condition in {attack, benign}
for N seeds, parses each episode's result, and aggregates the live H1 metrics:
  - decoy diversion rate (attack episodes)
  - mean defender cost (attack)
  - wasted cost on benign episodes (defense spent when no attack)
  - outcome breakdown
Physical-impact rate is NOT measured live (the testbed never executes the real
controller, by design); it stays the simulation result, reported separately.

  python3 pipeline/02_experiment_h1_live.py --episodes 20 --mode DYNAMIC_KG
  add --mock to validate the aggregation pipeline WITHOUT the testbed.
"""
from __future__ import annotations
import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "sphere" / "h1_live_episode.py"
POLICIES = ["MONITOR_ONLY", "FIXED_SCHEDULE", "STAGE_AGNOSTIC", "BELIEF_ADAPTIVE"]


def run_live(policy, mode, benign, env_pythonpath):
    """Invoke the live driver on the orchestration host; return its result dict."""
    cmd = [sys.executable, str(DRIVER), "--policy", policy, "--mode", mode]
    if benign:
        cmd.append("--benign")
    env = {"PYTHONPATH": env_pythonpath} if env_pythonpath else None
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          env={**__import__("os").environ, **(env or {})})
    for line in proc.stdout.splitlines():
        if line.startswith("H1_LIVE_EPISODE:"):
            return json.loads(line.split("H1_LIVE_EPISODE:", 1)[1])
    raise RuntimeError(f"episode failed ({policy},{'benign' if benign else 'attack'}):\n{proc.stdout[-500:]}\n{proc.stderr[-800:]}")


def mock_episode(policy, benign, rng):
    """Plausible live outcome for pipeline validation WITHOUT the testbed."""
    if benign:
        # Only a policy that arms deception on benign traffic wastes cost.
        wasted = {"MONITOR_ONLY": 0, "FIXED_SCHEDULE": 1, "STAGE_AGNOSTIC": 0,
                  "BELIEF_ADAPTIVE": 1 if rng.random() < 0.15 else 0}[policy]
        return {"policy": policy, "condition": "benign", "defender_cost": wasted,
                "decoy_diverted": False, "outcome": "BENIGN_NO_CONTROL"}
    div = {"MONITOR_ONLY": 0.0, "FIXED_SCHEDULE": 0.62, "STAGE_AGNOSTIC": 0.30,
           "BELIEF_ADAPTIVE": 0.55}[policy]
    cost = {"MONITOR_ONLY": 0, "FIXED_SCHEDULE": 2, "STAGE_AGNOSTIC": 2, "BELIEF_ADAPTIVE": 2}[policy]
    diverted = rng.random() < div
    return {"policy": policy, "condition": "attack", "defender_cost": cost,
            "decoy_diverted": diverted, "outcome": "DECOY_DIVERSION" if diverted else "CONTROL_WITHHELD"}


def aggregate(records):
    out = {}
    for p in POLICIES:
        atk = [r for r in records if r["policy"] == p and r["condition"] == "attack"]
        ben = [r for r in records if r["policy"] == p and r["condition"] == "benign"]
        out[p] = {
            "n_attack": len(atk), "n_benign": len(ben),
            "decoy_diversion_rate": (sum(r["decoy_diverted"] for r in atk) / len(atk)) if atk else None,
            "mean_cost_attack": (sum(r["defender_cost"] for r in atk) / len(atk)) if atk else None,
            "mean_wasted_cost_benign": (sum(r["defender_cost"] for r in ben) / len(ben)) if ben else None,
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=20, help="episodes per (policy, condition)")
    ap.add_argument("--mode", default="DYNAMIC_KG", choices=("NO_KG", "STATIC_KG", "DYNAMIC_KG"))
    ap.add_argument("--pythonpath", default="$HOME/ecpomdg:$HOME/ecpomdg_setup/multistage_game",
                    help="PYTHONPATH for the live driver on the testbed")
    ap.add_argument("--mock", action="store_true", help="validate aggregation without the testbed")
    ap.add_argument("--out", default=str(ROOT / "results" / "h1_live_results.json"))
    args = ap.parse_args()

    rng = random.Random(7)
    records, failures = [], 0
    for p in POLICIES:
        for benign in (False, True):
            for _ in range(args.episodes):
                try:
                    rec = mock_episode(p, benign, rng) if args.mock else run_live(p, args.mode, benign, args.pythonpath)
                    records.append(rec)
                except Exception as exc:
                    failures += 1
                    print(f"  WARN episode failed: {exc}", file=sys.stderr)

    summary = aggregate(records)
    report = {"experiment": "H1_live", "mode": args.mode, "episodes_per_cell": args.episodes,
              "source": "mock" if args.mock else "testbed", "n_records": len(records),
              "n_failures": failures, "policy_outcomes": summary,
              "note": "physical-impact not measured live (real controller never executes by design)"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")

    print(f"\nH1 LIVE ({report['source']}, {len(records)} episodes, {failures} failures)")
    print(f"{'policy':<16}{'divert(atk)':<13}{'cost(atk)':<11}{'wasted(benign)':<15}")
    for p in POLICIES:
        s = summary[p]
        dv = f"{s['decoy_diversion_rate']:.2f}" if s['decoy_diversion_rate'] is not None else "-"
        ca = f"{s['mean_cost_attack']:.2f}" if s['mean_cost_attack'] is not None else "-"
        wb = f"{s['mean_wasted_cost_benign']:.2f}" if s['mean_wasted_cost_benign'] is not None else "-"
        print(f"{p:<16}{dv:<13}{ca:<11}{wb:<15}")
    print(f"\nRESULT: {args.out}")


if __name__ == "__main__":
    main()
