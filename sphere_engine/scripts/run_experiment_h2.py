#!/usr/bin/env python3
"""Experiment B (H2): does graph context improve hidden-stage inference?

Trains one transparent categorical DBN per knowledge mode on a training split
of passive inference episodes, then evaluates held-out stage log-loss, Brier
score, and accuracy under TELEMETRY_ONLY / STATIC_KG / DYNAMIC_KG on the SAME
matched episodes. Reports paired-bootstrap confidence intervals for the
differences.

Every mode sees the identical raw event stream; modes differ only by which
KG-derived features the DBN is permitted to read. No evaluator label ever
enters a defender-visible feature.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecpomdg_final.dbn import CategoricalStageDBN
from ecpomdg_final.offline_kg import OfflineKG, EpisodeRuntimeGraph
from ecpomdg_final.simulator import SimConfig, generate_inference_episode, featurize
from ecpomdg_final.metrics import multiclass_brier, stage_log_loss, stage_accuracy, mean
from ecpomdg_final.stats import paired_bootstrap_diff
from ecpomdg_final.types import AttackerProfile, KnowledgeMode

MODES = ["TELEMETRY_ONLY", "STATIC_KG", "DYNAMIC_KG"]


def build_featurized_episodes(seeds, profiles, config):
    """Return list of episodes; each is a list of {true_stage, observation(full KG)}.

    Featurised once under DYNAMIC so every KG field is populated; each DBN then
    ignores the fields outside its own mode via Observation.features(mode).
    """
    kg = OfflineKG()
    episodes = []
    meta = []
    for profile in profiles:
        for seed in seeds:
            raw_turns = generate_inference_episode(seed, profile, config)
            runtime = EpisodeRuntimeGraph()
            ep = []
            for turn in raw_turns:
                obs = featurize(turn["raw_event"], kg, runtime, KnowledgeMode.DYNAMIC_KG)
                ep.append({"true_stage": turn["true_stage"], "observation": obs})
            episodes.append(ep)
            meta.append({"profile": str(AttackerProfile(profile).value), "seed": seed})
    return episodes, meta


def filter_episode(model: CategoricalStageDBN, episode):
    """Run the DBN forward filter; return per-turn (log_loss, brier, acc)."""
    posterior = None
    ll, br, ac = [], [], []
    for row in episode:
        result = model.update(posterior, row["observation"])
        posterior = result.posterior
        true_stage = row["true_stage"]
        ll.append(stage_log_loss(posterior, true_stage))
        br.append(multiclass_brier(posterior, true_stage))
        ac.append(stage_accuracy(posterior, true_stage))
    return ll, br, ac


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=400, help="episodes per attacker profile")
    parser.add_argument("--out", default=str(ROOT / "results" / "h2_inference.json"))
    args = parser.parse_args()

    config = SimConfig()
    profiles = ["CAUTIOUS", "PERSISTENT"]
    n = args.episodes
    all_seeds = list(range(1, n + 1))
    # Split by whole episode: 50% train, 20% val (unused for DBN fit here), 30% test.
    n_train = int(0.5 * n)
    n_val = int(0.2 * n)
    train_seeds = all_seeds[:n_train]
    val_seeds = all_seeds[n_train:n_train + n_val]
    test_seeds = all_seeds[n_train + n_val:]

    train_eps, _ = build_featurized_episodes(train_seeds, profiles, config)
    val_eps, _ = build_featurized_episodes(val_seeds, profiles, config)
    test_eps, test_meta = build_featurized_episodes(test_seeds, profiles, config)

    # Fit one DBN per mode on the SAME training episodes, then calibrate the
    # emission temperature on the validation split (never on test).
    models = {}
    temperatures = {}
    for m in MODES:
        model = CategoricalStageDBN(KnowledgeMode(m)).fit(train_eps)
        temperatures[m] = model.calibrate(val_eps)
        models[m] = model

    # Per-episode mean metrics (for pairing) and pooled per-turn metrics.
    per_episode = {m: {"log_loss": [], "brier": [], "accuracy": []} for m in MODES}
    pooled = {m: {"log_loss": [], "brier": [], "accuracy": []} for m in MODES}
    for m in MODES:
        for ep in test_eps:
            ll, br, ac = filter_episode(models[m], ep)
            per_episode[m]["log_loss"].append(mean(ll))
            per_episode[m]["brier"].append(mean(br))
            per_episode[m]["accuracy"].append(mean(ac))
            pooled[m]["log_loss"].extend(ll)
            pooled[m]["brier"].extend(br)
            pooled[m]["accuracy"].extend(ac)

    summary = {m: {k: mean(v) for k, v in pooled[m].items()} for m in MODES}

    # Paired bootstrap on per-episode mean log loss (primary endpoint).
    comparisons = {
        "STATIC_minus_TELEMETRY": paired_bootstrap_diff(per_episode["STATIC_KG"]["log_loss"], per_episode["TELEMETRY_ONLY"]["log_loss"]),
        "DYNAMIC_minus_TELEMETRY": paired_bootstrap_diff(per_episode["DYNAMIC_KG"]["log_loss"], per_episode["TELEMETRY_ONLY"]["log_loss"]),
        "DYNAMIC_minus_STATIC": paired_bootstrap_diff(per_episode["DYNAMIC_KG"]["log_loss"], per_episode["STATIC_KG"]["log_loss"]),
    }
    acc_comparisons = {
        "DYNAMIC_minus_TELEMETRY_accuracy": paired_bootstrap_diff(per_episode["DYNAMIC_KG"]["accuracy"], per_episode["TELEMETRY_ONLY"]["accuracy"]),
        "DYNAMIC_minus_STATIC_accuracy": paired_bootstrap_diff(per_episode["DYNAMIC_KG"]["accuracy"], per_episode["STATIC_KG"]["accuracy"]),
    }

    report = {
        "experiment": "H2_stage_inference",
        "config": config.__dict__,
        "episodes_per_profile": n,
        "profiles": profiles,
        "n_train_episodes": len(train_eps),
        "n_val_episodes": len(val_eps),
        "n_test_episodes": len(test_eps),
        "selected_temperatures": temperatures,
        "primary_endpoint": "stage_log_loss (lower is better)",
        "pooled_summary": summary,
        "log_loss_comparisons": comparisons,
        "accuracy_comparisons": acc_comparisons,
    }
    out = Path(args.out)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pooled_summary": summary, "log_loss_comparisons": comparisons}, indent=2))
    print(f"RESULT: {out}")


if __name__ == "__main__":
    main()
