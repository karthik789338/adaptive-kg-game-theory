#!/usr/bin/env python3
"""
EC-POMDG standalone engine + stage-conditioned extension (self-contained).

No external engine needed (pure Python stdlib). It is calibrated to reproduce the
deployed base-game Table I outcome rates, and adds a defender lever at EVERY
kill-chain stage so RECON and ACCESS stop being empty. Report: diversion /
withdrawn / contained-safe / compromise / mean reward + 95% bootstrap CIs, for
each policy x profile x budget.

LABEL FOR THE PAPER: these are standalone-engine numbers calibrated to the
deployed base rates; confirm against ec_pomdg on SPHERE before final submission.

    python3 ecpomdg_standalone.py --seeds 4000 --budgets 4 6
"""
from __future__ import annotations
import argparse, csv, random, statistics
from collections import Counter
from pathlib import Path

STAGES = ["RECON", "ACCESS", "DER_ENUM", "CONTROL", "IMPACT"]
HORIZON = 12

# --- calibrated parameters (match deployed base Table I rates) ---
P = {
    "CAUTIOUS":   dict(advance=0.68, p_ctrl=0.61, p_early=0.32,
                       w_recon=0.10, w_access=0.08),
    "PERSISTENT": dict(advance=0.82, p_ctrl=0.19, p_early=0.104,
                       w_recon=0.03, w_access=0.02),
}
HONEY_BOOST = 0.20
REDIRECT_CAP = 0.95
SAFETY_SUCCESS = 0.90
CONTAIN_DURATION = 2
EVADE_PROB = 0.85   # N1: deception-aware attacker evades an early-armed (fingerprinted) decoy

R = {"COMPROMISED_REAL": -100.0, "CONTAINED_SAFE": -10.0,
     "DIVERTED_DECOY": +12.0, "WITHDRAWN": 0.0}
COST = {"MONITOR": 0, "ACTIVATE_DECOY": 1, "REDIRECT": 1, "CONTAIN": 2,
        "DECEPTIVE_SURFACE": 1, "SESSION_CHALLENGE": 1, "HONEY_POINTS": 1,
        "SAFETY_INTERLOCK": 2}


# ----------------------------- policies -----------------------------
# Each returns an action given the (observable) state. Stage is known to the
# engine; policies that are "stage-blind early" simply never use it there.
def pol_monitor(st):
    return "MONITOR"

def pol_fixed(st):
    # non-adaptive: arm before control, ONE redirect at control. No fallback,
    # so a failed redirect leads to compromise.
    s = st["stage"]
    if not st["decoy"] and s in ("ACCESS", "DER_ENUM") and st["budget"] >= 1:
        return "ACTIVATE_DECOY"
    if st["decoy"] and s == "CONTROL" and not st["redirect_tried"] and st["budget"] >= 1:
        return "REDIRECT"
    return "MONITOR"

def pol_stage_agnostic(st):
    # greedy: arm asap, then redirect at EVERY eligible stage (no belief timing,
    # no containment fallback). Higher diversion, but residual -> compromise.
    if not st["decoy"] and st["budget"] >= 1:
        return "ACTIVATE_DECOY"
    if st["decoy"] and st["stage"] in ("ACCESS", "DER_ENUM", "CONTROL") and st["budget"] >= 1:
        return "REDIRECT"
    return "MONITOR"

def pol_belief(st):
    # belief-adaptive: arm before control, ONE well-timed redirect at control,
    # then well-timed CONTAIN as fallback (belief tells it exactly when), which
    # holds the attacker out of the horizon -> withdrawn. No compromise.
    s = st["stage"]
    if not st["decoy"] and s in ("DER_ENUM", "CONTROL") and st["budget"] >= 1:
        return "ACTIVATE_DECOY"
    if st["decoy"] and s == "CONTROL" and not st["redirect_tried"] and st["budget"] >= 1:
        return "REDIRECT"
    if st["redirect_tried"] and st["target"] == "REAL" and s in ("CONTROL", "IMPACT") and st["budget"] >= 2:
        return "CONTAIN"
    return "MONITOR"

def pol_stage_conditioned(st):
    # Defense-in-depth: a lever at every stage, while KEEPING the belief-adaptive
    # guarantee (redirect at control, contain fallback -> 0 compromise). Early
    # deception resolves a fraction of attacks before the control window; honey
    # points raise the control-window diversion. Budget is RESERVED for the
    # arm+redirect+contain bundle so early deception never starves it (needs B>=6).
    # A lever at every stage, with the decoy armed LATE (at DER_ENUM) so a
    # deception-aware attacker cannot fingerprint an early decoy (see N1):
    #   RECON   -> DECEPTIVE_SURFACE (early prevention)         [budget-gated]
    #   ACCESS  -> SESSION_CHALLENGE (slow + possible withdraw) [budget-gated]
    #   DER_ENUM-> HONEY_POINTS then ACTIVATE_DECOY (late arm)
    #   CONTROL -> REDIRECT ; fallback CONTAIN (0-compromise guarantee)
    s = st["stage"]; b = st["budget"]
    if s == "RECON" and not st["surf"] and b - 1 >= 4:          # reserve arm+redirect+contain
        return "DECEPTIVE_SURFACE"
    if not st["decoy"] and s in ("ACCESS", "DER_ENUM") and b >= 1:   # arm early -> free control window
        return "ACTIVATE_DECOY"
    if s == "DER_ENUM" and st["decoy"] and not st["honey"] and b - 1 >= 3:  # reserve redirect+contain
        return "HONEY_POINTS"
    if st["decoy"] and s == "CONTROL" and not st["redirect_tried"] and b >= 1:
        return "REDIRECT"
    # containment net: fire at control/impact whenever the attacker is still on
    # the real target (even if a redirect was evaded) -> 0 compromise.
    if st["target"] == "REAL" and s in ("CONTROL", "IMPACT") and b >= 2:
        return "CONTAIN"
    return "MONITOR"

POLICIES = {
    "MONITOR_ONLY": pol_monitor, "FIXED_SCHEDULE": pol_fixed,
    "STAGE_AGNOSTIC": pol_stage_agnostic, "BELIEF_ADAPTIVE": pol_belief,
    "STAGE_CONDITIONED": pol_stage_conditioned,
}


def episode(profile, policy, budget, rng, aware=False):
    # aware=True: a deception-AWARE attacker that fingerprints a decoy armed too
    # early (at RECON/ACCESS) and evades its redirect (N1). High-fidelity late
    # decoys and honey-points (indistinguishable from real enumeration) are not
    # detected.
    p = P[profile]
    st = dict(stage_i=0, stage="RECON", turn=0, budget=budget, decoy=False,
              arm_stage=None, honey=False, surf=False, chal=False,
              redirect_tried=False, target="REAL", contain=0, spent=0.0)
    while st["turn"] < HORIZON:
        st["stage"] = STAGES[st["stage_i"]]
        act = policy(st)
        c = COST[act]
        if c > st["budget"]:
            act, c = "MONITOR", 0
        st["budget"] -= c; st["spent"] += c
        slow = False

        if act == "ACTIVATE_DECOY":
            st["decoy"] = True; st["arm_stage"] = st["stage"]
        elif act == "HONEY_POINTS":
            st["honey"] = True
        elif act == "DECEPTIVE_SURFACE":
            st["surf"] = True; slow = True
            if rng.random() < p["w_recon"]:
                return "WITHDRAWN", R["WITHDRAWN"] - st["spent"]
        elif act == "SESSION_CHALLENGE":
            st["chal"] = True; slow = True
            if rng.random() < p["w_access"]:
                return "WITHDRAWN", R["WITHDRAWN"] - st["spent"]
        elif act == "CONTAIN":
            # well-timed containment at the control/impact window holds the
            # attacker out of the horizon -> withdrawal (no compromise).
            if st["stage"] in ("CONTROL", "IMPACT") and st["target"] == "REAL":
                return "WITHDRAWN", R["WITHDRAWN"] - st["spent"]
            st["contain"] = CONTAIN_DURATION
        elif act == "REDIRECT" and st["decoy"] and st["stage"] in ("ACCESS", "DER_ENUM", "CONTROL"):
            st["redirect_tried"] = True
            if st["stage"] == "CONTROL":
                pr = min(REDIRECT_CAP, p["p_ctrl"] + (HONEY_BOOST if st["honey"] else 0.0))
            else:
                pr = p["p_early"]
            # N1: a deception-aware attacker evades a decoy that was armed too
            # early (fingerprintable); late-armed decoys are not detected.
            if aware and st["arm_stage"] in ("RECON", "ACCESS"):
                pr *= (1.0 - EVADE_PROB)
            if rng.random() < pr:
                return "DIVERTED_DECOY", R["DIVERTED_DECOY"] - st["spent"]
        elif act == "SAFETY_INTERLOCK":
            if st["stage"] == "IMPACT" and st["target"] == "REAL" and rng.random() < SAFETY_SUCCESS:
                return "CONTAINED_SAFE", R["CONTAINED_SAFE"] - st["spent"]

        # ---- attacker transition ----
        if st["contain"] > 0:
            st["contain"] -= 1; st["turn"] += 1; continue
        if st["stage"] == "IMPACT":
            if st["target"] == "DECOY":
                return "DIVERTED_DECOY", R["DIVERTED_DECOY"] - st["spent"]
            return "COMPROMISED_REAL", R["COMPROMISED_REAL"] - st["spent"]
        adv = p["advance"] * (0.5 if slow else 1.0)
        if rng.random() < adv:
            st["stage_i"] += 1
        st["turn"] += 1
    return "WITHDRAWN", R["WITHDRAWN"] - st["spent"]   # horizon expired


def bootstrap_ci(vals, rng, reps=2000, alpha=0.05):
    n = len(vals)
    if n < 2:
        m = float(vals[0]) if vals else float("nan"); return m, m
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return means[int(alpha / 2 * reps)], means[int((1 - alpha / 2) * reps)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=4000, help="episodes per cell")
    ap.add_argument("--budgets", type=int, nargs="+", default=[4, 6])
    ap.add_argument("--attacker", choices=["fixed", "aware", "both"], default="fixed",
                    help="fixed = non-adaptive (base); aware = deception-aware adaptive (N1)")
    ap.add_argument("--outdir", default="results/stage_conditioned")
    args = ap.parse_args()
    out = Path(args.outdir); out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261116)
    modes = [("fixed", False), ("aware", True)] if args.attacker == "both" \
        else [(args.attacker, args.attacker == "aware")]

    rows = []
    for attacker, aware in modes:
        for profile in ("CAUTIOUS", "PERSISTENT"):
            for budget in args.budgets:
                for name, pol in POLICIES.items():
                    outc, rew = Counter(), []
                    for seed in range(args.seeds):   # paired seeds across policies
                        o, r = episode(profile, pol, budget, random.Random(seed), aware=aware)
                        outc[o] += 1; rew.append(r)
                    n = float(args.seeds)
                    lo, hi = bootstrap_ci(rew, rng)
                    rows.append(dict(attacker=attacker, profile=profile, budget=budget, policy=name,
                        diversion=outc["DIVERTED_DECOY"]/n, withdrawn=outc["WITHDRAWN"]/n,
                        contained_safe=outc["CONTAINED_SAFE"]/n, compromise=outc["COMPROMISED_REAL"]/n,
                        mean_reward=statistics.mean(rew), reward_ci_lo=lo, reward_ci_hi=hi))

    with open(out / "h1_stage_conditioned.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    hdr = f"{'attacker':9}{'profile':11}{'B':>2} {'policy':18}{'div':>6}{'wd':>6}{'comp':>6}{'reward [95% CI]':>22}"
    print(hdr); print("-"*len(hdr))
    for r in rows:
        print(f"{r['attacker']:9}{r['profile']:11}{r['budget']:>2} {r['policy']:18}{r['diversion']:6.2f}"
              f"{r['withdrawn']:6.2f}{r['compromise']:6.2f}   {r['mean_reward']:+7.2f} "
              f"[{r['reward_ci_lo']:+.1f},{r['reward_ci_hi']:+.1f}]")
    print(f"\nWrote {out}/h1_stage_conditioned.csv")


if __name__ == "__main__":
    main()
