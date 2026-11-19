#!/usr/bin/env python3
"""DYNAMIC-vs-STATIC replay experiment: the "seen a second time" proof.

This is the offline mirror of the SPHERE two-phase protocol and the core
argument that the *dynamic* knowledge graph beats the *static* one:

    Phase 1 (learn)  : run a set of attack/benign campaigns, adjudicate them,
                       and record each actor's confirmed outcome into campaign
                       memory (Neo4j on SPHERE; CampaignMemory here).
    Phase 2 (replay) : run fresh campaigns. A fraction of the actors RECUR
                       (they were seen in Phase 1); the rest are NOVEL. STATIC_KG
                       has no memory and must re-infer from ambiguous telemetry;
                       DYNAMIC_KG retrieves the prior campaign for the actor and
                       recognises the returning adversary immediately.

We expect DYNAMIC to beat STATIC overall, and by a larger margin on the
recurring-attacker episodes, with no benefit on novel actors (the honest bound:
the gain is proportional to recurrence). The belief filter is the six-state
(NORMAL + five) model so we can also measure detection lead time.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecpomdg_final.campaign_memory import CampaignMemory
from ecpomdg_final.dbn import CategoricalStageDBN
from ecpomdg_final.offline_kg import OfflineKG, EpisodeRuntimeGraph
from ecpomdg_final.simulator import SimConfig, generate_inference_episode, featurize
from ecpomdg_final.metrics import stage_log_loss, stage_accuracy, mean
from ecpomdg_final.stats import paired_bootstrap_diff
from ecpomdg_final.types import KnowledgeMode

SIX_STATES = ["NORMAL", "RECON", "ACCESS", "DER_ENUM", "CONTROL", "IMPACT"]
_RANK = {s: i for i, s in enumerate(SIX_STATES)}
PHASE1, PHASE2 = 1.0, 2.0


def _seed(actor: str, phase: int) -> int:
    return (abs(hash((actor, phase))) % 2_000_000_000) + 1


def _max_attack_stage(turns) -> str:
    best = "NORMAL"
    for t in turns:
        if t["true_stage"] != "NORMAL" and _RANK[t["true_stage"]] > _RANK[best]:
            best = t["true_stage"]
    return best


def build_phase(prefix: str, n_attack: int, n_benign: int, rec_frac: float, config: SimConfig):
    """Return (memory, phase2_episodes) for one disjoint actor population.

    phase2_episodes: list of dicts {actor, has_attacker, recurring, turns}.
    """
    memory = CampaignMemory()
    attack_actors = [(f"{prefix}-atk-{i}", "CAUTIOUS" if i % 2 else "PERSISTENT") for i in range(n_attack)]
    benign_actors = [f"{prefix}-ben-{i}" for i in range(n_benign)]

    def recurring(i, n):
        return i < int(rec_frac * n)

    # Phase 1: record the recurring subset's confirmed campaigns.
    for i, (actor, profile) in enumerate(attack_actors):
        if not recurring(i, n_attack):
            continue
        turns = generate_inference_episode(_seed(actor, 1), profile, config, has_attacker=True, actor_id=actor)
        memory.record_campaign(actor, True, _max_attack_stage(turns), asof=PHASE1)
    for i, actor in enumerate(benign_actors):
        if not recurring(i, n_benign):
            continue
        memory.record_campaign(actor, False, "NORMAL", asof=PHASE1)

    # Phase 2: a fresh campaign for every actor.
    episodes = []
    for i, (actor, profile) in enumerate(attack_actors):
        turns = generate_inference_episode(_seed(actor, 2), profile, config, has_attacker=True, actor_id=actor)
        episodes.append({"actor": actor, "has_attacker": True, "recurring": recurring(i, n_attack), "turns": turns})
    for i, actor in enumerate(benign_actors):
        turns = generate_inference_episode(_seed(actor, 2), "CAUTIOUS", config, has_attacker=False, actor_id=actor)
        episodes.append({"actor": actor, "has_attacker": False, "recurring": recurring(i, n_benign), "turns": turns})
    return memory, episodes


def featurize_episode(ep, kg, memory, mode):
    rt = EpisodeRuntimeGraph()
    use_mem = memory if mode == KnowledgeMode.DYNAMIC_KG else None
    return [{"true_stage": t["true_stage"],
             "observation": featurize(t["raw_event"], kg, rt, mode, memory=use_mem, asof=PHASE2)}
            for t in ep["turns"]]


def filter_metrics(model, feats):
    posterior = None
    ll, ac = [], []
    detect_turn = None
    for i, row in enumerate(feats):
        res = model.update(posterior, row["observation"])
        posterior = res.posterior
        ll.append(stage_log_loss(posterior, row["true_stage"]))
        ac.append(stage_accuracy(posterior, row["true_stage"]))
        if detect_turn is None and (1.0 - posterior.get("NORMAL", 0.0)) >= 0.5:
            detect_turn = i
    return mean(ll), mean(ac), (detect_turn if detect_turn is not None else len(feats))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attack-actors", type=int, default=160)
    parser.add_argument("--benign-actors", type=int, default=160)
    parser.add_argument("--recurrence", type=float, default=0.6, help="fraction of actors seen in Phase 1")
    parser.add_argument("--out", default=str(ROOT / "results" / "replay_dynamic_vs_static.json"))
    args = parser.parse_args()

    config = SimConfig()
    kg = OfflineKG()

    # Disjoint train and test actor populations (prior_campaign is a category,
    # so the learned emission generalises; actor ids are never features).
    train_mem, train_eps = build_phase("train", args.attack_actors, args.benign_actors, args.recurrence, config)
    test_mem, test_eps = build_phase("test", args.attack_actors, args.benign_actors, args.recurrence, config)

    models = {}
    for mode in (KnowledgeMode.STATIC_KG, KnowledgeMode.DYNAMIC_KG):
        feats = [featurize_episode(ep, kg, train_mem, mode) for ep in train_eps]
        models[mode] = CategoricalStageDBN(mode, stages=SIX_STATES).fit(feats)

    # Evaluate on the held-out test population.
    per = {m: {"ll": [], "acc": [], "detect_attack": [], "ll_rec_atk": [], "detect_rec_atk": []}
           for m in ("STATIC_KG", "DYNAMIC_KG")}
    for ep in test_eps:
        for mode in (KnowledgeMode.STATIC_KG, KnowledgeMode.DYNAMIC_KG):
            feats = featurize_episode(ep, kg, test_mem, mode)
            ll, ac, det = filter_metrics(models[mode], feats)
            key = mode.value
            per[key]["ll"].append(ll)
            per[key]["acc"].append(ac)
            if ep["has_attacker"]:
                per[key]["detect_attack"].append(det)
                if ep["recurring"]:
                    per[key]["ll_rec_atk"].append(ll)
                    per[key]["detect_rec_atk"].append(det)

    def summ(key):
        d = per[key]
        return {
            "log_loss": mean(d["ll"]),
            "accuracy": mean(d["acc"]),
            "mean_detection_turn_attack": mean(d["detect_attack"]),
            "log_loss_recurring_attacker": mean(d["ll_rec_atk"]),
            "mean_detection_turn_recurring_attacker": mean(d["detect_rec_atk"]),
        }

    report = {
        "experiment": "dynamic_vs_static_replay",
        "config": config.__dict__,
        "recurrence_fraction": args.recurrence,
        "actors": {"attack": args.attack_actors, "benign": args.benign_actors},
        "note": "STATIC has no campaign memory; DYNAMIC reads prior confirmed campaigns (asof < decision).",
        "STATIC_KG": summ("STATIC_KG"),
        "DYNAMIC_KG": summ("DYNAMIC_KG"),
        "paired_comparisons": {
            "log_loss_DYNAMIC_minus_STATIC_all": paired_bootstrap_diff(per["DYNAMIC_KG"]["ll"], per["STATIC_KG"]["ll"]),
            "log_loss_DYNAMIC_minus_STATIC_recurring_attacker": paired_bootstrap_diff(per["DYNAMIC_KG"]["ll_rec_atk"], per["STATIC_KG"]["ll_rec_atk"]),
            "detection_turn_DYNAMIC_minus_STATIC_recurring_attacker": paired_bootstrap_diff(per["DYNAMIC_KG"]["detect_rec_atk"], per["STATIC_KG"]["detect_rec_atk"]),
        },
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("STATIC_KG", "DYNAMIC_KG", "paired_comparisons")}, indent=2))
    print(f"RESULT: {args.out}")


if __name__ == "__main__":
    main()
