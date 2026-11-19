#!/usr/bin/env python3
"""Experiment C (joint): does the H2 inference gain translate into H1 outcome?

Runs the belief-adaptive policy in the closed-loop game under each knowledge
mode (TELEMETRY_ONLY / STATIC_KG / DYNAMIC_KG), each with its own
temperature-calibrated six-state belief filter and its own validation-tuned
thresholds. Reports overall defender utility and per-attack physical-impact
rate so any inference advantage can be read as an operational advantage.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_experiment_h1 import (
    train_frozen_dbn, run_episode, build_specs, select_belief_adaptive,
)
from ecpomdg_final.policies import BeliefAdaptivePolicy
from ecpomdg_final.simulator import SimConfig
from ecpomdg_final.stats import paired_bootstrap_diff, rate_ci
from ecpomdg_final.types import KnowledgeMode

MODES = ["TELEMETRY_ONLY", "STATIC_KG", "DYNAMIC_KG"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=500)
    parser.add_argument("--val", type=int, default=150)
    parser.add_argument("--out", default=str(ROOT / "results" / "joint_h1_h2.json"))
    args = parser.parse_args()

    config = SimConfig()
    profiles = ["CAUTIOUS", "PERSISTENT"]
    val_specs = build_specs(list(range(9001, 9001 + args.val)), profiles)
    test_specs = build_specs(list(range(1, args.episodes + 1)), profiles)

    records = {m: [] for m in MODES}
    tuned = {}
    for mode in MODES:
        dbn = train_frozen_dbn(config, KnowledgeMode(mode))
        params = select_belief_adaptive(val_specs, dbn, config)
        tuned[mode] = params
        policy = BeliefAdaptivePolicy(*params)
        for profile, seed, has_attacker in test_specs:
            records[mode].append(run_episode(seed, profile, policy, dbn, config, has_attacker))

    def util(mode):
        return [r["utility"] for r in records[mode]]

    def impact_attack(mode):
        return [r["physical_impact"] for r in records[mode] if r["has_attacker"] == 1]

    outcomes = {}
    for mode in MODES:
        recs = records[mode]
        attack = [r for r in recs if r["has_attacker"] == 1]
        outcomes[mode] = {
            "mean_utility_overall": sum(r["utility"] for r in recs) / len(recs),
            "physical_impact_rate_attack": rate_ci(sum(r["physical_impact"] for r in attack), len(attack)),
            "thresholds": tuned[mode],
        }

    comparisons = {
        "utility_DYNAMIC_minus_TELEMETRY": paired_bootstrap_diff(util("DYNAMIC_KG"), util("TELEMETRY_ONLY")),
        "utility_STATIC_minus_TELEMETRY": paired_bootstrap_diff(util("STATIC_KG"), util("TELEMETRY_ONLY")),
        "utility_DYNAMIC_minus_STATIC": paired_bootstrap_diff(util("DYNAMIC_KG"), util("STATIC_KG")),
        "impact_DYNAMIC_minus_TELEMETRY": paired_bootstrap_diff(impact_attack("DYNAMIC_KG"), impact_attack("TELEMETRY_ONLY")),
    }

    report = {
        "experiment": "C_joint_inference_to_operational",
        "config": config.__dict__,
        "profiles": profiles,
        "n_episodes_per_mode": len(test_specs),
        "mode_outcomes": outcomes,
        "paired_comparisons": comparisons,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"mode_outcomes": outcomes, "paired_comparisons": comparisons}, indent=2))
    print(f"RESULT: {args.out}")


if __name__ == "__main__":
    main()
