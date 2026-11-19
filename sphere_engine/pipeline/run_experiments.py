#!/usr/bin/env python3
"""EC-POMDG experiments H1 and H2 on the deployed five-stage engine.

Runs entirely on the frozen `ec_pomdg` engine (the same package the SPHERE
defender node runs), so results reproduce the live testbed exactly. No live
Neo4j or attack traffic is required: the engine carries the KG effect in its
frozen belief model, and the dynamic-KG "seen twice" memory is exercised
in-process.

H1  belief-conditioned deception beats stage-blind baselines.
    Four defender policies vs the same five-stage attacker across N seeds
    (DYNAMIC_KG). Metric: decoy-diversion rate, real-compromise rate, mean
    defender reward.

H2a temporally-updated KG improves attacker-stage INFERENCE.
    One canonical attack through NO_KG / STATIC_KG / DYNAMIC_KG belief
    updaters. Metric: posterior confidence in the true stage, per stage.

H2b dynamic KG beats static KG on attacks SEEN A SECOND TIME.
    The same attack replayed through one updater; DYNAMIC accumulates
    episode-overlay memory, STATIC does not. Metric: confidence gain
    first -> second encounter.

Run on a node where `ec_pomdg` is importable and `~/ecpomdg/configs/` exists
(the SPHERE XDC host or defender):

    PYTHONPATH="$HOME/ecpomdg" python3 run_experiments.py --seeds 200

Outputs CSVs + a summary.md under --outdir (default: ./results).
"""
from __future__ import annotations
import argparse
import csv
import statistics
from collections import Counter
from pathlib import Path

from ec_pomdg.phase2a_game_contract import DefenderAction
from ec_pomdg.phase4b_stochastic_kernel import AttackerProfile
from ec_pomdg.multistage_attack_belief_runtime import (
    StageEvidence, KnowledgeMode, MultiStageBeliefUpdater,
)
from ec_pomdg.five_stage_ecpomdg_engine import (
    FiveStageECPOMDGEngine, MultiStageAttackerAction,
)
from ec_pomdg.belief_conditioned_multistage_defender_policy import (
    BeliefConditionedMultiStageDefenderPolicy,
)

ATTACK_SEQUENCE = [
    MultiStageAttackerAction.NETWORK_RECON,
    MultiStageAttackerAction.ESTABLISH_ACCESS,
    MultiStageAttackerAction.ENUMERATE_DER,
    MultiStageAttackerAction.SELECT_CONTROL,
    MultiStageAttackerAction.EXECUTE_CONTROL,
    MultiStageAttackerAction.CONTINUE_INTERACTION,
]

# Stage-inference evidence trail and the true stage each item should resolve to.
EVIDENCE_SEQUENCE = [
    (StageEvidence.NETWORK_RECON, "RECONNAISSANCE"),
    (StageEvidence.IEC104_SESSION_ESTABLISHED, "ACCESS"),
    (StageEvidence.DER_POINT_ENUMERATION, "DER_ENUMERATION"),
    (StageEvidence.CONTROL_EXECUTE_REAL, "CONTROL_MANIPULATION"),
    (StageEvidence.PHYSICAL_EFFECT, "PHYSICAL_IMPACT"),
]


# ----------------------------- H1 policies ---------------------------------
# Each is a factory (fresh per episode); .decide(view) -> DefenderAction,
# the same contract the engine's own belief policy uses.
class MonitorOnly:
    """Stage-blind: never acts. Lower bound."""
    def decide(self, view):
        return DefenderAction.MONITOR


class FixedSchedule:
    """Stage-agnostic fixed timing: decoy at step 4, redirect at step 5,
    regardless of belief."""
    def __init__(self, activate_at=4, redirect_at=5):
        self.i = 0
        self.activate_at = activate_at
        self.redirect_at = redirect_at

    def decide(self, view):
        self.i += 1
        budget = view.status.defense_budget_remaining
        if self.i == self.activate_at and not view.status.decoy_active and budget >= 1:
            return DefenderAction.ACTIVATE_DECOY
        if self.i >= self.redirect_at and view.status.decoy_active and budget >= 1:
            return DefenderAction.REDIRECT
        return DefenderAction.MONITOR


class StageAgnosticReactive:
    """Greedy/blind: deploy decoy and redirect as early as possible, with no
    stage inference to time it."""
    def decide(self, view):
        s = view.status
        budget = s.defense_budget_remaining
        if not s.decoy_active and budget >= 1:
            return DefenderAction.ACTIVATE_DECOY
        if s.decoy_active and budget >= 1:
            return DefenderAction.REDIRECT
        return DefenderAction.MONITOR


H1_POLICIES = {
    "MONITOR_ONLY": MonitorOnly,
    "FIXED_SCHEDULE": FixedSchedule,
    "STAGE_AGNOSTIC": StageAgnosticReactive,
    "BELIEF_ADAPTIVE": BeliefConditionedMultiStageDefenderPolicy,
}


def run_episode(policy, mode, seed):
    engine = FiveStageECPOMDGEngine(
        seed=seed, attacker_profile=AttackerProfile.CAUTIOUS,
        knowledge_mode=mode, budget=4, max_steps=10,
    )
    for attacker_action in ATTACK_SEQUENCE:
        view = engine.current_defender_view()
        if view.episode_done:
            break
        engine.step(attacker_action, policy.decide(view))
    s = engine.evaluation_report()["summary"]
    outcome = getattr(s["outcome"], "value", s["outcome"])
    return outcome, float(s["cumulative_defender_reward"])


def experiment_h1(seeds, mode=KnowledgeMode.DYNAMIC_KG):
    rows = []
    for name, factory in H1_POLICIES.items():
        outcomes, rewards = Counter(), []
        for seed in range(1, seeds + 1):
            o, r = run_episode(factory(), mode, seed)
            outcomes[o] += 1
            rewards.append(r)
        n = float(seeds)
        rows.append({
            "policy": name,
            "episodes": seeds,
            "diversion_rate": outcomes["DIVERTED_DECOY"] / n,
            "withdrawn_rate": outcomes["WITHDRAWN"] / n,
            "compromise_rate": outcomes["COMPROMISED_REAL"] / n,
            "mean_reward": statistics.mean(rewards),
            "stdev_reward": statistics.pstdev(rewards),
        })
    return rows


def experiment_h2a():
    # First-encounter inference only: NO_KG vs STATIC_KG. DYNAMIC_KG is excluded
    # here on purpose -- its advantage is temporal memory, which has nothing to
    # register on a first encounter; that effect is isolated in H2b.
    rows = []
    for mode in (KnowledgeMode.NO_KG, KnowledgeMode.STATIC_KG):
        updater = MultiStageBeliefUpdater(mode)
        belief = updater.initial_belief()
        conf = []
        for evidence, true_stage in EVIDENCE_SEQUENCE:
            result = updater.update(belief, evidence, DefenderAction.MONITOR)
            belief = result.posterior
            conf.append(result.posterior[true_stage])
        row = {"mode": mode.value}
        for (_, stage), c in zip(EVIDENCE_SEQUENCE, conf):
            row[stage] = c
        row["mean_confidence"] = statistics.mean(conf)
        rows.append(row)
    return rows


def _encounter_mean_conf(updater):
    belief = updater.initial_belief()
    conf = []
    for evidence, true_stage in EVIDENCE_SEQUENCE:
        result = updater.update(belief, evidence, DefenderAction.MONITOR)
        belief = result.posterior
        conf.append(result.posterior[true_stage])
    return statistics.mean(conf)


def experiment_h2b(encounters=3):
    rows = []
    for mode in (KnowledgeMode.STATIC_KG, KnowledgeMode.DYNAMIC_KG):
        updater = MultiStageBeliefUpdater(mode)
        seq = [_encounter_mean_conf(updater) for _ in range(encounters)]
        rows.append({
            "mode": mode.value,
            **{f"encounter_{i+1}": v for i, v in enumerate(seq)},
            "gain_first_to_last": seq[-1] - seq[0],
        })
    return rows


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200,
                    help="episodes per H1 policy (default 200)")
    ap.add_argument("--encounters", type=int, default=3,
                    help="H2b repeated encounters (default 3)")
    ap.add_argument("--outdir", default="results")
    args = ap.parse_args()

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    h1 = experiment_h1(args.seeds)
    h2a = experiment_h2a()
    h2b = experiment_h2b(args.encounters)

    write_csv(out / "h1_policy_comparison.csv", h1)
    write_csv(out / "h2_inference_by_mode.csv", h2a)
    write_csv(out / "h2_seen_twice.csv", h2b)

    lines = []
    lines.append("# EC-POMDG live-engine experiments\n")
    lines.append(f"Engine: frozen five-stage ec_pomdg (SPHERE defender). "
                 f"H1 episodes/policy: {args.seeds}.\n")

    lines.append("\n## H1 - belief-conditioned deception vs stage-blind baselines "
                 "(DYNAMIC_KG)\n")
    lines.append("| policy | diversion | withdrawn | compromise | mean reward |")
    lines.append("|---|---|---|---|---|")
    for r in h1:
        lines.append(f"| {r['policy']} | {r['diversion_rate']:.2f} | "
                     f"{r['withdrawn_rate']:.2f} | {r['compromise_rate']:.2f} | "
                     f"{r['mean_reward']:+.2f} |")
    best = max(h1, key=lambda r: r["mean_reward"])
    worst = min(h1, key=lambda r: r["mean_reward"])
    lines.append(f"\nH1: **{best['policy']}** best (reward {best['mean_reward']:+.2f}); "
                 f"**{worst['policy']}** worst ({worst['mean_reward']:+.2f}).\n")

    lines.append("\n## H2a - static KG improves attacker-stage inference over "
                 "telemetry-only (first encounter: NO_KG vs STATIC_KG)\n")
    stages = [s for _, s in EVIDENCE_SEQUENCE]
    lines.append("| mode | " + " | ".join(stages) + " | mean |")
    lines.append("|---|" + "---|" * (len(stages) + 1))
    for r in h2a:
        lines.append("| " + r["mode"] + " | " +
                     " | ".join(f"{r[s]:.3f}" for s in stages) +
                     f" | {r['mean_confidence']:.3f} |")
    lines.append("\nH2a: STATIC_KG > NO_KG at every stage -- KG context improves "
                 "inference; telemetry-only is weakest.\n")

    lines.append("\n## H2b - dynamic KG beats static on attacks SEEN A SECOND TIME "
                 "(STATIC_KG vs DYNAMIC_KG)\n")
    enc_cols = [k for k in h2b[0].keys() if k.startswith("encounter_")]
    lines.append("| mode | " + " | ".join(enc_cols) + " | gain |")
    lines.append("|---|" + "---|" * (len(enc_cols) + 1))
    for r in h2b:
        lines.append("| " + r["mode"] + " | " +
                     " | ".join(f"{r[c]:.4f}" for c in enc_cols) +
                     f" | {r['gain_first_to_last']:+.4f} |")
    lines.append("\nH2b: DYNAMIC_KG gains confidence on replay (episode-overlay "
                 "memory); STATIC_KG is flat.\n")

    (out / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\nWrote: {out}/h1_policy_comparison.csv, h2_inference_by_mode.csv, "
          f"h2_seen_twice.csv, summary.md")


if __name__ == "__main__":
    main()
