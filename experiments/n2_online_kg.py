#!/usr/bin/env python3
"""
N2 -- Online-KG Bayesian likelihood (closing the open loop in EC-POMDG).

The paper's belief filter uses a KG-conditioned observation likelihood
Z_kappa = phi_kappa * Z_0. In the deployed engine phi_kappa is fixed up front
(STATIC_KG / frozen DYNAMIC_KG): the knowledge graph tells the defender how
observations map to stages, but that mapping is never corrected against what the
defender actually sees during the campaign. This script tests whether updating
phi_kappa ONLINE -- a running Dirichlet estimate of the true emission matrix --
produces a better-calibrated stage belief than the frozen mapping, with the same
observations.

It is a self-contained 5-stage HMM inference simulation (pure stdlib). The ground
truth is a left-to-right stage process (RECON..PHYSICAL) with a stage-correlated
but noisy observation channel. Three knowledge modes share the SAME observation
stream per episode (paired), so differences are purely the likelihood model:

  NO_KG      : uninformative likelihood (observations ignored) -> prior-only belief
  STATIC_KG  : frozen, mildly-miscalibrated emission matrix (the paper's setting)
  ONLINE_KG  : starts from the SAME frozen matrix, then updates it online from
               (observation, MAP-stage) counts with Laplace smoothing

Metrics per step, averaged over episodes:
  p_true   : belief mass on the true stage  (higher = better)
  brier    : multiclass Brier score of the belief vs the true stage (lower = better)
  acc      : MAP-stage accuracy             (higher = better)
  xent     : cross-entropy -log b(true)     (lower = better)

Run:
    python3 n2_online_kg.py --episodes 4000 --seed 7
"""
from __future__ import annotations
import argparse, csv, math, random
from pathlib import Path

STAGES = ["RECON", "ACCESS", "DER_ENUM", "CONTROL", "PHYSICAL"]
N = len(STAGES)
OBS = list(range(N))            # one observation symbol class per stage

# --- ground-truth dynamics ---------------------------------------------------
ADVANCE = 0.55                  # per-turn probability the true stage advances
# true emission: obs correlates with stage, diagonal-heavy but noisy
TRUE_EMIT_DIAG = 0.60
def true_emit(stage):
    off = (1.0 - TRUE_EMIT_DIAG) / (N - 1)
    return [TRUE_EMIT_DIAG if o == stage else off for o in OBS]

# frozen KG mapping the defender is handed: a generic / stale graph. It has the
# right diagonal shape but is only weakly discriminative (close to uniform) and is
# shifted toward the next stage -- i.e. it does not match the deployed feeder's real
# observation channel. This is the paper's STATIC_KG / frozen-DYNAMIC_KG setting.
FROZEN_DIAG = 0.34
FROZEN_SHIFT = 0.08             # leaks probability to the NEXT stage's symbol
def frozen_emit(stage):
    row = [0.0] * N
    base = (1.0 - FROZEN_DIAG) / (N - 1)
    for o in OBS:
        row[o] = FROZEN_DIAG if o == stage else base
    nxt = min(stage + 1, N - 1)
    row[nxt] += FROZEN_SHIFT
    s = sum(row)
    return [x / s for x in row]

def oracle_emit(stage):         # Bayes-optimal: the true channel (upper bound)
    return true_emit(stage)


def normalize(v):
    s = sum(v)
    return [x / s for x in v] if s > 0 else [1.0 / len(v)] * len(v)


def transition(stage, rng):
    if stage < N - 1 and rng.random() < ADVANCE:
        return stage + 1
    return stage


def bayes_step(belief, obs, emit_row_fn):
    """One predict+update step. emit_row_fn(stage) -> P(obs|stage) row."""
    # predict with the (known) left-to-right transition model
    pred = [0.0] * N
    for s in range(N):
        pred[s] += belief[s] * (1 - ADVANCE if s < N - 1 else 1.0)
        if s > 0:
            pred[s] += belief[s - 1] * ADVANCE
    # update with the likelihood
    post = [pred[s] * emit_row_fn(s)[obs] for s in range(N)]
    return normalize(post)


class OnlineEmit:
    """Dirichlet(Laplace) online estimate of the emission matrix, seeded from the
    frozen KG as a weak prior and corrected by FORENSICALLY-CONFIRMED (obs, stage)
    pairs revealed at the end of each campaign. It never self-labels from its own
    belief (that would reinforce its own errors), so the estimate converges toward
    the true emission channel instead of a fixed point of the frozen KG."""
    def __init__(self, prior_strength=3.0):
        self.counts = [[frozen_emit(s)[o] * prior_strength for o in OBS] for s in range(N)]
    def row(self, stage):
        return normalize(self.counts[stage])
    def observe(self, obs, true_stage):
        self.counts[true_stage][obs] += 1.0


def brier(belief, true_stage):
    return sum((belief[s] - (1.0 if s == true_stage else 0.0)) ** 2 for s in range(N))


def run_episode(rng, online):
    """Scores the three belief filters on one shared observation stream, using the
    online emission matrix as it stands at the START of the episode (learned from
    all prior campaigns). Returns the per-mode scores AND the confirmed (obs, stage)
    trace, which the caller feeds back to `online` only after the episode ends --
    i.e. post-campaign forensic labels, never mid-episode self-labels."""
    stage = 0
    steps = 0
    b_no = [1.0 / N] * N
    b_st = [1.0 / N] * N
    b_on = [1.0 / N] * N
    b_or = [1.0 / N] * N
    rec = {"NO_KG": [], "STATIC_KG": [], "ONLINE_KG": [], "ORACLE_KG": []}
    trace = []
    while steps < 12:
        obs = random.Random(rng.random()).choices(OBS, weights=true_emit(stage))[0]
        b_no = bayes_step(b_no, obs, lambda s: [1.0 / N] * N)   # uninformative
        b_st = bayes_step(b_st, obs, frozen_emit)
        b_on = bayes_step(b_on, obs, online.row)
        b_or = bayes_step(b_or, obs, oracle_emit)
        trace.append((obs, stage))            # confirmed only at campaign end
        for name, b in (("NO_KG", b_no), ("STATIC_KG", b_st),
                        ("ONLINE_KG", b_on), ("ORACLE_KG", b_or)):
            acc = 1.0 if max(range(N), key=lambda s: b[s]) == stage else 0.0
            xent = -math.log(max(b[stage], 1e-9))
            rec[name].append((b[stage], brier(b, stage), acc, xent))
        nxt = transition(stage, rng)
        steps += 1
        if stage == N - 1 and nxt == N - 1:
            break
        stage = nxt
    return rec, trace


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--outdir", default="results/n2")
    args = ap.parse_args()
    out = Path(args.outdir); out.mkdir(parents=True, exist_ok=True)

    agg = {m: [0.0, 0.0, 0.0, 0.0, 0] for m in ("NO_KG", "STATIC_KG", "ONLINE_KG", "ORACLE_KG")}
    online = OnlineEmit()                       # carries across episodes (campaign-level learning)
    for ep in range(args.episodes):
        rng = random.Random(args.seed * 100003 + ep)
        rec, trace = run_episode(rng, online)
        for m, rows in rec.items():
            for (pt, br, ac, xe) in rows:
                agg[m][0] += pt; agg[m][1] += br; agg[m][2] += ac; agg[m][3] += xe; agg[m][4] += 1
        for (obs, true_stage) in trace:            # post-campaign forensic correction
            online.observe(obs, true_stage)

    rows = []
    for m in ("NO_KG", "STATIC_KG", "ONLINE_KG", "ORACLE_KG"):
        n = agg[m][4]
        rows.append({"mode": m, "p_true": agg[m][0] / n, "brier": agg[m][1] / n,
                     "acc": agg[m][2] / n, "xent": agg[m][3] / n, "steps": n})
    with open(out / "n2_online_kg.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    hdr = f"{'mode':11}{'p_true':>8}{'brier':>8}{'acc':>8}{'xent':>8}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        print(f"{r['mode']:11}{r['p_true']:8.3f}{r['brier']:8.3f}{r['acc']:8.3f}{r['xent']:8.3f}")
    print(f"\nHigher p_true/acc, lower brier/xent = better-calibrated stage belief.")
    print(f"Wrote {out}/n2_online_kg.csv")


if __name__ == "__main__":
    main()
