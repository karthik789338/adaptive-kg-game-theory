#!/usr/bin/env python3
"""
H1 extension: stage-conditioned defender vs the base policies, over a budget sweep
and BOTH attacker profiles, on the deployed ec_pomdg engine.

Mirrors run_experiments.py's engine usage exactly, adds the STAGE_CONDITIONED
policy, parameterizes budget and profile, and reports diversion / withdrawn /
contained_safe / compromise / mean-reward with 95% bootstrap CIs.

    PYTHONPATH="$HOME/ecpomdg" python3 run_experiments_extended.py \
        --seeds 200 --budgets 4 6 --outdir results/stage_conditioned

Requires the engine changes in STAGE_CONDITIONED_ENGINE_PATCH.md (new actions +
CONTAINED_SAFE terminal). Base policies are included so the table is self-contained
and so you can confirm they are unchanged by the patch.
"""
from __future__ import annotations
import argparse, csv, random, statistics
from collections import Counter
from pathlib import Path

from ec_pomdg.phase2a_game_contract import DefenderAction
from ec_pomdg.phase4b_stochastic_kernel import AttackerProfile
from ec_pomdg.multistage_attack_belief_runtime import KnowledgeMode
from ec_pomdg.five_stage_ecpomdg_engine import (
    FiveStageECPOMDGEngine, MultiStageAttackerAction,
)
from ec_pomdg.belief_conditioned_multistage_defender_policy import (
    BeliefConditionedMultiStageDefenderPolicy,
)
from stage_conditioned_policy import StageConditionedDefenderPolicy

ATTACK_SEQUENCE = [
    MultiStageAttackerAction.NETWORK_RECON,
    MultiStageAttackerAction.ESTABLISH_ACCESS,
    MultiStageAttackerAction.ENUMERATE_DER,
    MultiStageAttackerAction.SELECT_CONTROL,
    MultiStageAttackerAction.EXECUTE_CONTROL,
    MultiStageAttackerAction.CONTINUE_INTERACTION,
]


class MonitorOnly:
    def decide(self, view): return DefenderAction.MONITOR


class FixedSchedule:
    def __init__(self, activate_at=4, redirect_at=5):
        self.i = 0; self.activate_at = activate_at; self.redirect_at = redirect_at
    def decide(self, view):
        self.i += 1; b = view.status.defense_budget_remaining
        if self.i == self.activate_at and not view.status.decoy_active and b >= 1:
            return DefenderAction.ACTIVATE_DECOY
        if self.i >= self.redirect_at and view.status.decoy_active and b >= 1:
            return DefenderAction.REDIRECT
        return DefenderAction.MONITOR


class StageAgnosticReactive:
    def decide(self, view):
        s = view.status; b = s.defense_budget_remaining
        if not s.decoy_active and b >= 1: return DefenderAction.ACTIVATE_DECOY
        if s.decoy_active and b >= 1: return DefenderAction.REDIRECT
        return DefenderAction.MONITOR


POLICIES = {
    "MONITOR_ONLY": MonitorOnly,
    "FIXED_SCHEDULE": FixedSchedule,
    "STAGE_AGNOSTIC": StageAgnosticReactive,
    "BELIEF_ADAPTIVE": BeliefConditionedMultiStageDefenderPolicy,
    "STAGE_CONDITIONED": StageConditionedDefenderPolicy,
}


def run_episode(policy, profile, budget, seed, mode=KnowledgeMode.DYNAMIC_KG):
    engine = FiveStageECPOMDGEngine(seed=seed, attacker_profile=profile,
                                    knowledge_mode=mode, budget=budget, max_steps=10)
    for attacker_action in ATTACK_SEQUENCE:
        view = engine.current_defender_view()
        if view.episode_done:
            break
        engine.step(attacker_action, policy.decide(view))
    s = engine.evaluation_report()["summary"]
    outcome = getattr(s["outcome"], "value", s["outcome"])
    return outcome, float(s["cumulative_defender_reward"])


def bootstrap_ci(vals, rng, reps=2000, alpha=0.05):
    n = len(vals)
    if n < 2:
        m = float(vals[0]) if vals else float("nan"); return m, m
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return means[int(alpha / 2 * reps)], means[int((1 - alpha / 2) * reps)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--budgets", type=int, nargs="+", default=[4, 6])
    ap.add_argument("--outdir", default="results/stage_conditioned")
    args = ap.parse_args()
    out = Path(args.outdir); out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261116)

    rows = []
    for profile in (AttackerProfile.CAUTIOUS, AttackerProfile.PERSISTENT):
        for budget in args.budgets:
            for name, factory in POLICIES.items():
                outc, rew = Counter(), []
                for seed in range(1, args.seeds + 1):
                    o, r = run_episode(factory(), profile, budget, seed)
                    outc[o] += 1; rew.append(r)
                n = float(args.seeds)
                lo, hi = bootstrap_ci(rew, rng)
                rows.append({
                    "profile": profile.value, "budget": budget, "policy": name,
                    "diversion": outc["DIVERTED_DECOY"] / n,
                    "withdrawn": outc["WITHDRAWN"] / n,
                    "contained_safe": outc.get("CONTAINED_SAFE", 0) / n,
                    "compromise": outc["COMPROMISED_REAL"] / n,
                    "mean_reward": statistics.mean(rew),
                    "reward_ci_lo": lo, "reward_ci_hi": hi,
                })

    with open(out / "h1_stage_conditioned.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    hdr = f"{'profile':11}{'B':>3} {'policy':18}{'div':>6}{'wd':>6}{'safe':>6}{'comp':>6}{'reward [95% CI]':>22}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        print(f"{r['profile']:11}{r['budget']:>3} {r['policy']:18}{r['diversion']:6.2f}{r['withdrawn']:6.2f}"
              f"{r['contained_safe']:6.2f}{r['compromise']:6.2f}   {r['mean_reward']:+7.2f} "
              f"[{r['reward_ci_lo']:+.1f},{r['reward_ci_hi']:+.1f}]")
    print(f"\nWrote {out}/h1_stage_conditioned.csv")


if __name__ == "__main__":
    main()
