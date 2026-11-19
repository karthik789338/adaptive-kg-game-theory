#!/usr/bin/env python3
"""SPHERE live pipeline CLI: synth -> learn -> eval (dynamic vs static).

Runs the two-phase campaign-replay protocol against real (or synthesised)
collector telemetry, using Neo4j as the persistent campaign store when a URI is
given and a local JSON store otherwise. The same inference (`dbn.py`), KG
features (`offline_kg.py`), and campaign memory (`campaign_memory.py`) used in
the offline experiments drive the live run, so results are directly comparable.

Two actor populations are used, exactly as in the offline replay experiment:

  * ``train`` — a calibration round used only to FIT the belief filters. It has
    its own Phase-1 (recorded) and Phase-2 campaigns, so the filter learns the
    emission for returning (KNOWN_ATTACKER/BENIGN) and novel (UNKNOWN) actors.
  * ``test``  — the held-out evaluation round, scored under STATIC and DYNAMIC.

Subcommands
-----------
  synth                 Build train/ and test/ Phase-1 and Phase-2 NDJSON
                        telemetry streams (dry-run/CI; on SPHERE the collector's
                        defender_observation_events.jsonl replaces these).
  learn {train|test}    Record that population's Phase-1 campaigns into its store
                        (Neo4j database ecpomdg_<pop>, or data/store_<pop>.json).
  eval                  Fit STATIC+DYNAMIC six-state filters on train/Phase-2
                        (train store), score test/Phase-2 (test store), write the
                        comparison. DYNAMIC reads the campaign store; STATIC does
                        not.

Telemetry schema (one JSON object per line, defender-visible only):
  {"event_type","protocol_phase","target_role","physical_alarm",
   "asset_id","source_host","actor_id","collector_ts_utc"}
Evaluator labels live in a separate <stream>.labels.json and are NEVER read by
the defender featurisation.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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


# ---- store abstraction (Neo4j on SPHERE, JSON file offline) ---------------
class _JsonStore:
    def __init__(self, path):
        self.path = Path(path)
        self.mem = CampaignMemory.load_json(self.path)

    def record(self, actor, is_attack, max_stage, asof):
        self.mem.record_campaign(actor, is_attack, max_stage, asof)
        self.mem.save_json(self.path)

    def prior_campaign(self, actor, asof):
        return self.mem.prior_campaign(actor, asof)


def open_store(args, population):
    if getattr(args, "neo4j_uri", None):
        from ecpomdg_final.campaign_memory import Neo4jCampaignMemory

        class _Neo:
            def __init__(self):
                # Community Edition: single `neo4j` database; separate populations
                # by a `population` property (Enterprise could use separate DBs).
                self.m = Neo4jCampaignMemory(args.neo4j_uri, args.neo4j_user, args.neo4j_password,
                                             database="neo4j", population=population)

            def record(self, actor, is_attack, max_stage, asof):
                self.m.record_campaign(actor, is_attack, max_stage, f"{asof:019.6f}")

            def prior_campaign(self, actor, asof):
                return self.m.prior_campaign(actor, f"{asof:019.6f}")
        return _Neo()
    return _JsonStore(Path(args.store_dir) / f"store_{population}.json")


# ---- stream helpers -------------------------------------------------------
def _max_attack_stage(stages):
    best = "NORMAL"
    for s in stages:
        if s != "NORMAL" and _RANK[s] > _RANK[best]:
            best = s
    return best


def write_stream(stream_dir: Path, actor: str, turns):
    stream_dir.mkdir(parents=True, exist_ok=True)
    with (stream_dir / f"{actor}.ndjson").open("w") as fh:
        for t in turns:
            fh.write(json.dumps(t["raw_event"]) + "\n")
    labels = {"actor_id": actor,
              "is_attack": any(t["true_stage"] != "NORMAL" for t in turns),
              "true_stages": [t["true_stage"] for t in turns]}
    (stream_dir / f"{actor}.labels.json").write_text(json.dumps(labels) + "\n")


def read_stream(ev_path: Path):
    events = [json.loads(l) for l in ev_path.read_text().splitlines() if l.strip()]
    labels = json.loads((ev_path.parent / f"{ev_path.stem}.labels.json").read_text())
    return events, labels


def featurize_stream(events, kg, store, mode, asof):
    rt = EpisodeRuntimeGraph()
    mem = store if (mode == KnowledgeMode.DYNAMIC_KG and store is not None) else None
    return [featurize(ev, kg, rt, mode, memory=mem, asof=asof) for ev in events]


def _emit_population(base: Path, prefix, n_atk, n_ben, rec, config):
    atk = [(f"{prefix}-atk-{i}", "CAUTIOUS" if i % 2 else "PERSISTENT") for i in range(n_atk)]
    ben = [f"{prefix}-ben-{i}" for i in range(n_ben)]
    seed = lambda a, ph: (abs(hash((a, ph))) % 2_000_000_000) + 1
    recurring = lambda i, n: i < int(rec * n)
    p1, p2 = base / "phase1", base / "phase2"
    for i, (a, prof) in enumerate(atk):
        if recurring(i, n_atk):
            write_stream(p1, a, generate_inference_episode(seed(a, 1), prof, config, True, a))
        write_stream(p2, a, generate_inference_episode(seed(a, 2), prof, config, True, a))
    for i, a in enumerate(ben):
        if recurring(i, n_ben):
            write_stream(p1, a, generate_inference_episode(seed(a, 1), "CAUTIOUS", config, False, a))
        write_stream(p2, a, generate_inference_episode(seed(a, 2), "CAUTIOUS", config, False, a))


# ---- subcommands ----------------------------------------------------------
def cmd_synth(args):
    config = SimConfig()
    base = Path(args.streams)
    for pop in ("train", "test"):
        _emit_population(base / pop, pop, args.attack_actors, args.benign_actors, args.recurrence, config)
    print(f"SYNTH: wrote train/ and test/ phase1+phase2 streams under {base} "
          f"({args.attack_actors} attack + {args.benign_actors} benign actors each, recurrence={args.recurrence})")


def cmd_learn(args):
    store = open_store(args, args.population)
    p1 = Path(args.streams) / args.population / "phase1"
    n = 0
    for ev_path in sorted(p1.glob("*.ndjson")):
        _, labels = read_stream(ev_path)
        store.record(labels["actor_id"], labels["is_attack"], _max_attack_stage(labels["true_stages"]), PHASE1)
        n += 1
    print(f"LEARN[{args.population}]: recorded {n} Phase-1 campaigns")


def cmd_eval(args):
    kg = OfflineKG()
    train_store = open_store(args, "train")
    test_store = open_store(args, "test")
    base = Path(args.streams)

    # Fit STATIC + DYNAMIC on train/phase2 (train store supplies priors).
    models = {}
    for mode in (KnowledgeMode.STATIC_KG, KnowledgeMode.DYNAMIC_KG):
        eps = []
        for ev_path in sorted((base / "train" / "phase2").glob("*.ndjson")):
            events, labels = read_stream(ev_path)
            feats = featurize_stream(events, kg, train_store, mode, PHASE2)
            eps.append([{"true_stage": s, "observation": o} for s, o in zip(labels["true_stages"], feats)])
        models[mode] = CategoricalStageDBN(mode, stages=SIX_STATES).fit(eps)

    recurring_actors = {ev.stem for ev in (base / "test" / "phase1").glob("*.ndjson")}
    per = {m: {"ll": [], "acc": [], "ll_rec_atk": [], "det_rec_atk": []} for m in ("STATIC_KG", "DYNAMIC_KG")}
    for ev_path in sorted((base / "test" / "phase2").glob("*.ndjson")):
        events, labels = read_stream(ev_path)
        recurring = ev_path.stem in recurring_actors
        for mode in (KnowledgeMode.STATIC_KG, KnowledgeMode.DYNAMIC_KG):
            feats = featurize_stream(events, kg, test_store, mode, PHASE2)
            posterior, ll, ac, det = None, [], [], None
            for i, (s, o) in enumerate(zip(labels["true_stages"], feats)):
                posterior = models[mode].update(posterior, o).posterior
                ll.append(stage_log_loss(posterior, s)); ac.append(stage_accuracy(posterior, s))
                if det is None and (1.0 - posterior.get("NORMAL", 0.0)) >= 0.5:
                    det = i
            key = mode.value
            per[key]["ll"].append(mean(ll)); per[key]["acc"].append(mean(ac))
            if labels["is_attack"] and recurring:
                per[key]["ll_rec_atk"].append(mean(ll))
                per[key]["det_rec_atk"].append(det if det is not None else len(feats))

    def summ(k):
        d = per[k]
        return {"log_loss": mean(d["ll"]), "accuracy": mean(d["acc"]),
                "log_loss_recurring_attacker": mean(d["ll_rec_atk"]),
                "mean_detection_turn_recurring_attacker": mean(d["det_rec_atk"])}

    report = {
        "experiment": "sphere_live_dynamic_vs_static_replay",
        "store": "neo4j" if getattr(args, "neo4j_uri", None) else f"json:{args.store_dir}",
        "STATIC_KG": summ("STATIC_KG"),
        "DYNAMIC_KG": summ("DYNAMIC_KG"),
        "paired_comparisons": {
            "log_loss_DYNAMIC_minus_STATIC_all": paired_bootstrap_diff(per["DYNAMIC_KG"]["ll"], per["STATIC_KG"]["ll"]),
            "log_loss_DYNAMIC_minus_STATIC_recurring_attacker": paired_bootstrap_diff(per["DYNAMIC_KG"]["ll_rec_atk"], per["STATIC_KG"]["ll_rec_atk"]),
            "detection_turn_DYNAMIC_minus_STATIC_recurring_attacker": paired_bootstrap_diff(per["DYNAMIC_KG"]["det_rec_atk"], per["STATIC_KG"]["det_rec_atk"]),
        },
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("STATIC_KG", "DYNAMIC_KG", "paired_comparisons")}, indent=2))
    print(f"RESULT: {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--streams", default=str(ROOT / "data" / "streams"))
    ap.add_argument("--store-dir", default=str(ROOT / "data"))
    ap.add_argument("--neo4j-uri", default=None, help="e.g. bolt://10.50.0.30:7687 (SPHERE kg node)")
    ap.add_argument("--neo4j-user", default="neo4j")
    ap.add_argument("--neo4j-password", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synth")
    s.add_argument("--attack-actors", type=int, default=120)
    s.add_argument("--benign-actors", type=int, default=120)
    s.add_argument("--recurrence", type=float, default=0.6)
    s.set_defaults(func=cmd_synth)

    le = sub.add_parser("learn")
    le.add_argument("population", choices=["train", "test"])
    le.set_defaults(func=cmd_learn)

    ev = sub.add_parser("eval")
    ev.add_argument("--out", default=str(ROOT / "results" / "sphere_live_replay.json"))
    ev.set_defaults(func=cmd_eval)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
