#!/usr/bin/env python3
"""
N3 -- Cyber-physical coupling: physical risk as a defensive decision variable.

EC-POMDG so far rewards cyber outcomes (compromise / divert / withdraw). But the
reason compromise matters is PHYSICAL: a malicious DER setpoint on the real
controller moves feeder voltages. This script couples the game outcome to a linear
power-flow sensitivity model of an IEEE-13-like feeder and asks a sharper question:
given a limited deception budget, WHERE should the defender place its decoys?

A linear voltage-sensitivity model gives worst-bus deviation for a malicious real-
power setpoint swing dP at a DER bus:  |dV|_worst = S_bus * dP   (pu).
A deviation above the ANSI-style band (|dV| > 0.05 pu) is a violation.

A rational attacker aims for maximum physical impact, so it preferentially targets
the HIGHEST-sensitivity DER bus. The defender's decoy can convincingly cover only a
budget B of the DER buses (arming a believable decoy setpoint at each costs budget).
If the attacker's target bus is covered, the command is diverted to the decoy and
the physical effect is zero; otherwise the real swing lands.

Policies compared (all at the same budget B):
  NO_DECEPTION   : cover nothing (monitor-only baseline)
  RANDOM_COVER   : stage-blind -- cover B buses at random
  PHYSICS_AWARE  : cover the B HIGHEST-sensitivity buses (couples game to physics)
  FULL_COVER     : belief-adaptive deception that reaches every control point
                   (the base-game 0-compromise result; shown as the ceiling)

Metrics over many seeded attacks: violation rate, mean worst |dV| (pu), p95 |dV|.

Run:
    python3 n3_cyber_physical.py --attacks 20000 --budgets 2 4 --seed 11

For a real (non-linear) power-flow confirmation on the SPHERE/EC2 testbed, the same
experiment runs against OpenDSS -- see the runbook printed at the end / the README.
"""
from __future__ import annotations
import argparse, csv, random, statistics
from pathlib import Path

# IEEE-13-like feeder: DER buses and their worst-bus voltage sensitivity (pu / kW).
# Plausible radial-feeder values; the ordering (which bus hurts most) is what matters.
SENS = {
    "675": 3.1e-4,   # far end, weak -> most sensitive
    "671": 2.8e-4,
    "680": 2.4e-4,
    "684": 1.9e-4,
    "652": 1.5e-4,
    "645": 1.2e-4,   # near substation -> stiff
}
BUSES = list(SENS.keys())
VIOLATION_PU = 0.05          # ANSI-style deviation band
DP_MIN, DP_MAX = 60.0, 180.0  # malicious DER real-power setpoint swing (kW)
ATTACKER_SHARPNESS = 3.0     # >1 => attacker favors high-sensitivity buses


def attacker_target(rng):
    """Rational attacker: target bus chosen with weight ~ sensitivity^sharpness."""
    weights = [SENS[b] ** ATTACKER_SHARPNESS for b in BUSES]
    return rng.choices(BUSES, weights=weights)[0]


def covered_set(policy, budget, rng):
    if policy == "NO_DECEPTION":
        return set()
    if policy == "FULL_COVER":
        return set(BUSES)
    if policy == "PHYSICS_AWARE":
        return set(sorted(BUSES, key=lambda b: SENS[b], reverse=True)[:budget])
    if policy == "RANDOM_COVER":
        return set(rng.sample(BUSES, min(budget, len(BUSES))))
    raise ValueError(policy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attacks", type=int, default=20000)
    ap.add_argument("--budgets", type=int, nargs="+", default=[2, 4])
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--outdir", default="results/n3")
    args = ap.parse_args()
    out = Path(args.outdir); out.mkdir(parents=True, exist_ok=True)

    policies = ["NO_DECEPTION", "RANDOM_COVER", "PHYSICS_AWARE", "FULL_COVER"]
    rows = []
    for budget in args.budgets:
        for pol in policies:
            dvs, viol = [], 0
            for i in range(args.attacks):
                rng = random.Random(args.seed * 1_000_003 + budget * 101 + i)
                # fixed cover per (policy,budget) seed so RANDOM is a fair single draw per attack
                cov = covered_set(pol, budget, random.Random(args.seed * 7 + budget * 13 + i))
                tgt = attacker_target(rng)
                dp = rng.uniform(DP_MIN, DP_MAX)
                dv = 0.0 if tgt in cov else SENS[tgt] * dp
                dvs.append(dv)
                if dv > VIOLATION_PU:
                    viol += 1
            dvs_sorted = sorted(dvs)
            p95 = dvs_sorted[int(0.95 * (len(dvs_sorted) - 1))]
            rows.append({
                "budget": budget, "policy": pol,
                "violation_rate": viol / args.attacks,
                "mean_dv_pu": statistics.mean(dvs),
                "p95_dv_pu": p95,
            })

    with open(out / "n3_cyber_physical.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    hdr = f"{'B':>3} {'policy':14}{'violation':>11}{'mean|dV|pu':>12}{'p95|dV|pu':>11}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        print(f"{r['budget']:>3} {r['policy']:14}{r['violation_rate']:11.3f}"
              f"{r['mean_dv_pu']:12.4f}{r['p95_dv_pu']:11.4f}")
    print(f"\nViolation = worst-bus |dV| > {VIOLATION_PU} pu. Lower is safer.")
    print(f"Wrote {out}/n3_cyber_physical.csv")


if __name__ == "__main__":
    main()
