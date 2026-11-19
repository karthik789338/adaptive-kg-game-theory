#!/usr/bin/env python3
"""7-mask knowledge-graph ablation: which of the 3 KGs drives stage inference?

Static features come from the real Neo4j KGs via data/kg_tables.json
(build it with scripts/live/build_kg_tables.py; --synthetic for offline). Each
KG contributes one feature group:

    G (general_cyber)     -> cyber_tactic         (ATT&CK tactic bucket)
    I (power_grid_ics)    -> ics_stage_hint        (IEC-104 behavior -> stage)
    T (component_topology)-> topology_risk + source_trust

Masks evaluated (same population, matched): NONE, G, I, T, G_I, G_T, I_T, G_I_T.
NONE is raw telemetry only (event_type, protocol_phase, physical_alarm). Every
mask also always includes raw telemetry. Primary endpoint: held-out stage
log-loss; paired bootstrap vs NONE. experiment_evidence and EC3D2C synthetic
nodes are excluded from static at table-build time.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecpomdg_final.dbn import CategoricalStageDBN
from ecpomdg_final.campaign_memory import CampaignMemory
from ecpomdg_final.simulator import SimConfig, generate_inference_episode
from ecpomdg_final.metrics import stage_log_loss, stage_accuracy, mean
from ecpomdg_final.stats import paired_bootstrap_diff

SIX = ["NORMAL", "RECON", "ACCESS", "DER_ENUM", "CONTROL", "IMPACT"]
_RANK = {s: i for i, s in enumerate(SIX)}
PHASE1, PHASE2 = 1.0, 2.0
MASKS = ["NONE", "G", "I", "T", "G_I", "G_T", "I_T", "G_I_T"]
GROUP_FEATURES = {
    "G": ["kg_cyber_tactic"],
    "I": ["kg_ics_stage_hint"],
    "T": ["kg_topology_risk", "kg_source_trust"],
}


class _Obs:
    """Thin observation whose features() returns the mask-selected dict."""
    __slots__ = ("feats",)

    def __init__(self, feats):
        self.feats = feats

    def features(self, mode):  # mode ignored; mask already applied
        return self.feats


def event_features(raw, tables):
    """All KG feature groups for one raw event, from the tables."""
    ev = raw["event_type"]
    asset = raw.get("asset_id", "UNKNOWN")
    src = raw.get("source_host", "UNKNOWN")
    return {
        "base": {"event_type": ev, "protocol_phase": raw.get("protocol_phase", "NONE"),
                 "physical_alarm": raw.get("physical_alarm", "NO")},
        "kg_topology_risk": tables["topology_risk"].get(asset, "UNKNOWN"),
        "kg_source_trust": tables["source_trust"].get(src, "UNKNOWN"),
        "kg_ics_stage_hint": tables["ics_stage_hint"].get(ev, "IDLE"),
        "kg_cyber_tactic": tables["cyber_tactic"].get(ev, "none"),
    }


def select(feats_all, mask):
    out = dict(feats_all["base"])
    if mask != "NONE":
        for g in mask.split("_"):
            for f in GROUP_FEATURES[g]:
                out[f] = feats_all[f]
    return out


def make_population(seeds, config, tables):
    """Mixed attack/benign episodes; each turn carries all-group features."""
    eps = []
    for i, seed in enumerate(seeds):
        for profile in ("CAUTIOUS", "PERSISTENT"):
            has_attacker = (i % 2 == 0)
            raw_turns = generate_inference_episode(seed, profile, config, has_attacker=has_attacker)
            eps.append([{"true_stage": t["true_stage"], "all": event_features(t["raw_event"], tables)}
                        for t in raw_turns])
    return eps


def fit_eval(train, val, test, mask):
    def wrap(eps):
        return [[{"true_stage": r["true_stage"], "observation": _Obs(select(r["all"], mask))} for r in ep]
                for ep in eps]
    model = CategoricalStageDBN("DYNAMIC_KG", stages=SIX).fit(wrap(train))
    model.calibrate(wrap(val))
    per_ll, per_acc = [], []
    for ep in wrap(test):
        post, ll, ac = None, [], []
        for r in ep:
            post = model.update(post, r["observation"]).posterior
            ll.append(stage_log_loss(post, r["true_stage"]))
            ac.append(stage_accuracy(post, r["true_stage"]))
        per_ll.append(mean(ll)); per_acc.append(mean(ac))
    return per_ll, per_acc


# --- dynamic (campaign-memory) extension: Phase-1 record -> Phase-2 replay -----
def _open_store(population):
    """Neo4j campaign store when NEO4J_PASSWORD is set, else in-memory."""
    pw = os.environ.get("NEO4J_PASSWORD")
    if pw:
        try:
            from ecpomdg_final.campaign_memory import Neo4jCampaignMemory
            m = Neo4jCampaignMemory(os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
                                    os.environ.get("NEO4J_USER", "neo4j"), pw,
                                    database="neo4j", population=f"ablation_{population}")
            return m, True
        except Exception:
            pass
    return CampaignMemory(), False


def _max_attack_stage(stages):
    best = "NORMAL"
    for s in stages:
        if s != "NORMAL" and _RANK[s] > _RANK[best]:
            best = s
    return best


def _seed(actor, phase):
    return (abs(hash((actor, phase))) % 2_000_000_000) + 1


def build_recurring(prefix, config, tables, n_atk, n_ben, rec):
    """Phase-1 records campaigns into a store; Phase-2 replays same+novel actors.

    Returns (episodes, store, is_neo4j) where each turn carries all KG features
    AND the actor's prior-campaign label read from the store (as-of Phase-2).
    """
    store, is_neo4j = _open_store(prefix)
    attack = [(f"{prefix}-atk-{i}", "CAUTIOUS" if i % 2 else "PERSISTENT") for i in range(n_atk)]
    benign = [f"{prefix}-ben-{i}" for i in range(n_ben)]
    recurring = lambda i, n: i < int(rec * n)

    def rec_campaign(actor, is_attack, stage):
        asof = f"{PHASE1:019.6f}" if is_neo4j else PHASE1
        store.record_campaign(actor, is_attack, stage, asof)

    for i, (a, prof) in enumerate(attack):
        if recurring(i, n_atk):
            turns = generate_inference_episode(_seed(a, 1), prof, config, True, a)
            rec_campaign(a, True, _max_attack_stage([t["true_stage"] for t in turns]))
    for i, a in enumerate(benign):
        if recurring(i, n_ben):
            rec_campaign(a, False, "NORMAL")

    cutoff = f"{PHASE2:019.6f}" if is_neo4j else PHASE2

    def prior(a):
        return store.prior_campaign(a, cutoff)

    eps = []
    for i, (a, prof) in enumerate(attack):
        turns = generate_inference_episode(_seed(a, 2), prof, config, True, a)
        eps.append([{"true_stage": t["true_stage"], "all": event_features(t["raw_event"], tables),
                     "prior": prior(a)} for t in turns])
    for i, a in enumerate(benign):
        turns = generate_inference_episode(_seed(a, 2), "CAUTIOUS", config, False, a)
        eps.append([{"true_stage": t["true_stage"], "all": event_features(t["raw_event"], tables),
                     "prior": prior(a)} for t in turns])
    return eps, is_neo4j


def _dyn_wrap(eps, mask, dynamic):
    out = []
    for ep in eps:
        rows = []
        for r in ep:
            feats = select(r["all"], mask)
            if dynamic:
                feats = dict(feats)
                feats["kg_prior_campaign"] = r["prior"]
            rows.append({"true_stage": r["true_stage"], "observation": _Obs(feats)})
        out.append(rows)
    return out


def fit_eval_dyn(train, val, test, mask, dynamic):
    model = CategoricalStageDBN("DYNAMIC_KG", stages=SIX).fit(_dyn_wrap(train, mask, dynamic))
    model.calibrate(_dyn_wrap(val, mask, dynamic))
    per_ll = []
    for ep in _dyn_wrap(test, mask, dynamic):
        post, ll = None, []
        for r in ep:
            post = model.update(post, r["observation"]).posterior
            ll.append(stage_log_loss(post, r["true_stage"]))
        per_ll.append(mean(ll))
    return per_ll


def run_dynamic(tables, config, n_atk, n_ben, rec, out):
    train, _ = build_recurring("abl-train", config, tables, n_atk, n_ben, rec)
    val, _ = build_recurring("abl-val", config, tables, n_atk // 2, n_ben // 2, rec)
    test, is_neo4j = build_recurring("abl-test", config, tables, n_atk, n_ben, rec)
    store_kind = "neo4j" if is_neo4j else "in-memory"
    rows, report = {}, {}
    for mask in MASKS:
        static_ll = fit_eval_dyn(train, val, test, mask, dynamic=False)
        dyn_ll = fit_eval_dyn(train, val, test, mask, dynamic=True)
        lift = paired_bootstrap_diff(dyn_ll, static_ll)
        rows[mask] = (mean(static_ll), mean(dyn_ll), lift)
        report[mask] = {"static_log_loss": mean(static_ll), "dynamic_log_loss": mean(dyn_ll),
                        "dynamic_minus_static": lift}
    Path(out).write_text(json.dumps(
        {"experiment": "kg_ablation_static_vs_dynamic", "store": store_kind,
         "tables_source": tables.get("_provenance", {}).get("source"), "per_mask": report}, indent=2) + "\n")
    print(f"campaign store: {store_kind}   (dynamic = Phase-1 recorded, same actors replayed in Phase-2)")
    print(f"{'mask':<8}{'static_ll':<12}{'dynamic_ll':<12}{'dyn-static (CI)':<30}")
    for mask in MASKS:
        st, dy, lift = rows[mask]
        sig = "sig" if lift["ci_high"] < 0 else "ns"
        print(f"{mask:<8}{st:<12.4f}{dy:<12.4f}{lift['mean_diff']:+.4f} "
              f"[{lift['ci_low']:+.4f},{lift['ci_high']:+.4f}] {sig}")
    print(f"\nRESULT: {out}  (store: {store_kind})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", default="data/kg_tables.json")
    ap.add_argument("--episodes", type=int, default=300, help="seeds per split block")
    ap.add_argument("--dynamic", action="store_true",
                    help="add the campaign-memory column: static vs dynamic per KG mask (uses Neo4j if NEO4J_PASSWORD set)")
    ap.add_argument("--out", default=str(ROOT / "results" / "kg_ablation.json"))
    args = ap.parse_args()

    tpath = Path(args.tables)
    if not tpath.exists():
        raise SystemExit(f"{tpath} not found. Build it first:\n"
                         f"  python3 scripts/live/build_kg_tables.py [--synthetic]")
    tables = json.loads(tpath.read_text())
    config = SimConfig()

    if args.dynamic:
        run_dynamic(tables, config, n_atk=120, n_ben=120, rec=0.6,
                    out=str(Path(args.out).with_name("kg_ablation_dynamic.json")))
        return

    n = args.episodes
    train = make_population(range(1, n + 1), config, tables)
    val = make_population(range(n + 1, n + 1 + n // 2), config, tables)
    test = make_population(range(n + 1 + n // 2, 2 * n + 1 + n // 2), config, tables)

    results, per_mask_ll = {}, {}
    for mask in MASKS:
        ll, acc = fit_eval(train, val, test, mask)
        per_mask_ll[mask] = ll
        results[mask] = {"log_loss": mean(ll), "accuracy": mean(acc), "n_test_episodes": len(ll)}

    comparisons = {}
    for mask in MASKS:
        if mask == "NONE":
            continue
        comparisons[f"{mask}_minus_NONE"] = paired_bootstrap_diff(per_mask_ll[mask], per_mask_ll["NONE"])

    report = {"experiment": "kg_7mask_ablation", "tables_source": tables.get("_provenance", {}),
              "primary_endpoint": "stage_log_loss (lower better)", "per_mask": results,
              "log_loss_vs_NONE": comparisons}
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")

    print(f"{'mask':<8}{'log_loss':<11}{'accuracy':<10}{'vs NONE (CI)':<28}")
    for mask in MASKS:
        r = results[mask]
        if mask == "NONE":
            tag = "(baseline)"
        else:
            c = comparisons[f"{mask}_minus_NONE"]
            sig = "sig" if c["ci_high"] < 0 else ("sig+" if c["ci_low"] > 0 else "ns")
            tag = f"{c['mean_diff']:+.4f} [{c['ci_low']:+.4f},{c['ci_high']:+.4f}] {sig}"
        print(f"{mask:<8}{r['log_loss']:<11.4f}{r['accuracy']:<10.4f}{tag:<28}")
    print(f"\nRESULT: {args.out}  (tables source: {tables.get('_provenance',{}).get('source')})")


if __name__ == "__main__":
    main()
