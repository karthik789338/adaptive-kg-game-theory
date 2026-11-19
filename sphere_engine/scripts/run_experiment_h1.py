#!/usr/bin/env python3
"""Experiment A (H1): does belief-conditioned adaptive defense improve resilience?

One inference configuration (a temperature-calibrated DYNAMIC_KG DBN) is frozen,
then the closed-loop five-stage game is run under each defender policy on matched
seeds and matched attacker profiles. The emission stream and attacker progression
are paired across policies at each seed, so differences reflect the policy, not
luck.

Primary endpoint: physical-impact rate (lower is better). Secondary: real
compromise, decoy diversion, mean defense cost, mean defender utility.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecpomdg_final.dbn import CategoricalStageDBN
from ecpomdg_final.game import FiveStageMarkovGame
from ecpomdg_final.offline_kg import OfflineKG, EpisodeRuntimeGraph
from ecpomdg_final.simulator import SimConfig, generate_inference_episode, featurize
from ecpomdg_final.policies import (
    MonitorOnlyPolicy, FixedSchedulePolicy, StageAgnosticReactivePolicy, BeliefAdaptivePolicy,
)
from ecpomdg_final.stats import paired_bootstrap_diff, rate_ci
from ecpomdg_final.types import AttackerProfile, DefenderView, KnowledgeMode

POLICIES = {
    "MONITOR_ONLY": MonitorOnlyPolicy,
    "FIXED_SCHEDULE": FixedSchedulePolicy,
    "STAGE_AGNOSTIC": StageAgnosticReactivePolicy,
    "BELIEF_ADAPTIVE": BeliefAdaptivePolicy,
}


SIX_STATES = ["NORMAL", "RECON", "ACCESS", "DER_ENUM", "CONTROL", "IMPACT"]


def train_frozen_dbn(config: SimConfig, mode: KnowledgeMode = KnowledgeMode.DYNAMIC_KG) -> CategoricalStageDBN:
    """Six-state (NORMAL + five attack stages) belief filter for ``mode``.

    Trained on a mix of attack and attack-free episodes so the filter can hold
    belief in NORMAL when no adversary is present, which is what lets a
    belief-conditioned policy avoid spending defense on quiet operations. Every
    mode is trained on the same episodes; feature gating happens in the DBN.
    """
    kg = OfflineKG()
    train, val = [], []
    for profile in ("CAUTIOUS", "PERSISTENT"):
        for seed in range(5001, 5161):
            has_attacker = (seed % 2 == 0)  # half attack-free
            raw = generate_inference_episode(seed, profile, config, has_attacker=has_attacker)
            rt = EpisodeRuntimeGraph()
            ep = [{"true_stage": t["true_stage"],
                   "observation": featurize(t["raw_event"], kg, rt, KnowledgeMode.DYNAMIC_KG)}
                  for t in raw]
            (train if seed < 5121 else val).append(ep)
    model = CategoricalStageDBN(KnowledgeMode(mode), stages=SIX_STATES).fit(train)
    model.calibrate(val)
    return model


def run_episode(seed, profile, policy, dbn, config, has_attacker=True):
    game = FiveStageMarkovGame(seed, profile, budget=4, has_attacker=has_attacker)
    kg = OfflineKG()
    runtime = EpisodeRuntimeGraph()
    posterior = None
    previous = None
    turns = 0
    while not game.done and turns < config.max_turns:
        raw = game.observe_raw(config)
        obs = featurize(raw, kg, runtime, KnowledgeMode.DYNAMIC_KG)
        update = dbn.update(posterior, obs)
        posterior = update.posterior
        view = DefenderView(
            belief=posterior, observation=obs, public_state=game.public_state(),
            previous_action=previous, turn=game.turn,
        )
        action = policy.decide(view)
        game.apply_defender(action)
        previous = action.value
        game.attacker_transition()
        game.tick_operational(config)
        turns += 1
    o = game.outcome
    return {
        "has_attacker": int(has_attacker),
        "physical_impact": int(o.physical_impact),
        "compromised_real": int(o.compromised_real),
        "diverted_decoy": int(o.diverted_decoy),
        "defense_cost": game.defense_cost,
        "operational_cost": game.operational_cost,
        "utility": game.utility(),
    }


def build_specs(seeds, profiles, attack_free_fraction=0.5):
    """Deterministic (profile, seed, has_attacker) specs shared by all policies."""
    specs = []
    for profile in profiles:
        for i, seed in enumerate(seeds):
            has_attacker = (i % 2 == 0) if attack_free_fraction == 0.5 else (i / len(seeds) >= attack_free_fraction)
            specs.append((profile, seed, has_attacker))
    return specs


def mean_utility(policy, specs, dbn, config):
    total = 0.0
    for profile, seed, has_attacker in specs:
        total += run_episode(seed, profile, policy, dbn, config, has_attacker)["utility"]
    return total / len(specs)


def select_fixed_schedule(val_specs, dbn, config):
    best, best_u = None, -1e18
    for a in (1, 2, 3):
        for r in (3, 4, 5):
            for c in (5, 6, 7):
                u = mean_utility(FixedSchedulePolicy(a, r, c), val_specs, dbn, config)
                if u > best_u:
                    best_u, best = u, (a, r, c)
    return best


def select_belief_adaptive(val_specs, dbn, config):
    best, best_u = None, -1e18
    for a in (0.40, 0.55, 0.70):
        for r in (0.25, 0.35, 0.50):
            for c in (0.45, 0.55, 0.65):
                u = mean_utility(BeliefAdaptivePolicy(a, r, c), val_specs, dbn, config)
                if u > best_u:
                    best_u, best = u, (a, r, c)
    return best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=500, help="TEST seeds per attacker profile")
    parser.add_argument("--val", type=int, default=150, help="validation seeds per profile for tuning")
    parser.add_argument("--out", default=str(ROOT / "results" / "h1_closed_loop.json"))
    args = parser.parse_args()

    config = SimConfig()
    dbn = train_frozen_dbn(config)
    profiles = ["CAUTIOUS", "PERSISTENT"]
    # Disjoint validation (tuning) and test (reporting) seed blocks.
    val_specs = build_specs(list(range(9001, 9001 + args.val)), profiles)
    test_specs = build_specs(list(range(1, args.episodes + 1)), profiles)

    fixed_params = select_fixed_schedule(val_specs, dbn, config)
    belief_params = select_belief_adaptive(val_specs, dbn, config)
    policy_instances = {
        "MONITOR_ONLY": MonitorOnlyPolicy(),
        "FIXED_SCHEDULE": FixedSchedulePolicy(*fixed_params),
        "STAGE_AGNOSTIC": StageAgnosticReactivePolicy(),
        "BELIEF_ADAPTIVE": BeliefAdaptivePolicy(*belief_params),
    }

    # Collect per-episode records on the held-out test specs, matched by spec.
    records = {p: [] for p in POLICIES}
    for policy_name, policy in policy_instances.items():
        for profile, seed, has_attacker in test_specs:
            records[policy_name].append(run_episode(seed, profile, policy, dbn, config, has_attacker))

    def series(name, key, subset=None):
        return [r[key] for r in records[name] if subset is None or r["has_attacker"] == subset]

    rates = {}
    for name in POLICIES:
        recs = records[name]
        n = len(recs)
        attack = [r for r in recs if r["has_attacker"] == 1]
        quiet = [r for r in recs if r["has_attacker"] == 0]
        rates[name] = {
            # Impact/diversion are only meaningful when an attacker is present.
            "physical_impact_rate_attack": rate_ci(sum(r["physical_impact"] for r in attack), len(attack)),
            "decoy_diversion_rate_attack": rate_ci(sum(r["diverted_decoy"] for r in attack), len(attack)),
            "mean_utility_attack": sum(r["utility"] for r in attack) / max(1, len(attack)),
            # Attack-free episodes expose wasted defensive spend (false deployment).
            "mean_wasted_cost_quiet": sum(r["defense_cost"] + r["operational_cost"] for r in quiet) / max(1, len(quiet)),
            "mean_utility_quiet": sum(r["utility"] for r in quiet) / max(1, len(quiet)),
            # Overall is the headline: defend when attacked, stay cheap when quiet.
            "mean_utility_overall": sum(r["utility"] for r in recs) / n,
        }

    # Paired comparisons: BELIEF_ADAPTIVE vs each baseline (impact & utility).
    comparisons = {}
    for baseline in ["MONITOR_ONLY", "FIXED_SCHEDULE", "STAGE_AGNOSTIC"]:
        comparisons[f"utility_overall_BELIEF_minus_{baseline}"] = paired_bootstrap_diff(
            series("BELIEF_ADAPTIVE", "utility"), series(baseline, "utility"))
        comparisons[f"impact_attack_BELIEF_minus_{baseline}"] = paired_bootstrap_diff(
            series("BELIEF_ADAPTIVE", "physical_impact", subset=1), series(baseline, "physical_impact", subset=1))

    report = {
        "experiment": "H1_closed_loop_policy_comparison",
        "config": config.__dict__,
        "frozen_inference": "DYNAMIC_KG DBN, temperature-calibrated",
        "selected_hyperparameters": {
            "FIXED_SCHEDULE_turns": fixed_params,
            "BELIEF_ADAPTIVE_thresholds": belief_params,
            "selection": "max mean utility on disjoint validation seeds",
        },
        "episodes_per_profile": args.episodes,
        "profiles": profiles,
        "n_episodes_per_policy": len(records["BELIEF_ADAPTIVE"]),
        "primary_endpoint": "physical_impact_rate (lower is better)",
        "policy_outcomes": rates,
        "paired_comparisons": comparisons,
    }
    out = Path(args.out)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"policy_outcomes": rates}, indent=2))
    print(f"RESULT: {out}")


if __name__ == "__main__":
    main()
