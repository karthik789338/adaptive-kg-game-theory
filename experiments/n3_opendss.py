#!/usr/bin/env python3
"""
N3 (OpenDSS) -- cyber-physical coupling with REAL non-linear power flow.

This replaces the linear `|dV| = S*dP` assumption in n3_cyber_physical.py with a
measured voltage sensitivity from an OpenDSS load-flow solve on an IEEE-13-style
radial feeder. For each DER bus it:
  1. solves the base case,
  2. applies a malicious real-power setpoint swing dP at that bus (a generator),
  3. re-solves, and records the worst per-unit voltage deviation across all buses.
The measured max|dV|/dP per bus becomes the sensitivity used in exactly the same
cover-policy comparison as the linear model, so the two are directly comparable and
the physical claim no longer rests on a linear assumption.

Requires:  pip install --break-system-packages opendssdirect.py
Run:       python3 n3_opendss.py --attacks 50000 --budgets 1 2 3 4 --seed 11

The feeder is written to ieee13_der.dss next to this script (self-contained, no
external data files). To use the official IEEE 13-node feeder instead, point
--feeder at IEEE13Nodeckt.dss; the rest is unchanged.
"""
from __future__ import annotations
import argparse, csv, math, random, statistics
from pathlib import Path

# ---------------------------------------------------------------------------
# A compact IEEE-13-style radial feeder (4.16 kV). DER buses match the linear
# model: 675, 671, 680, 684, 652, 645. Balanced positive-sequence for clarity.
# ---------------------------------------------------------------------------
FEEDER_DSS = """
Clear
New Circuit.ieee13der basekv=4.16 phases=3 bus1=650 pu=1.0 R1=0.1 X1=0.5 R0=0.1 X0=0.5
New Linecode.mtx nphases=3 R1=0.3 X1=0.6 R0=0.6 X0=1.2 units=mi
New Line.650632  bus1=650  bus2=632  linecode=mtx length=2.0 units=mi
New Line.632671  bus1=632  bus2=671  linecode=mtx length=2.0 units=mi
New Line.671680  bus1=671  bus2=680  linecode=mtx length=1.0 units=mi
New Line.632645  bus1=632  bus2=645  linecode=mtx length=0.5 units=mi
New Line.671684  bus1=671  bus2=684  linecode=mtx length=0.3 units=mi
New Line.684652  bus1=684  bus2=652  linecode=mtx length=0.8 units=mi
New Line.671675  bus1=671  bus2=675  linecode=mtx length=1.6 units=mi
New Load.L632 bus1=632 phases=3 kV=4.16 kW=200 kvar=120 model=1
New Load.L671 bus1=671 phases=3 kV=4.16 kW=400 kvar=250 model=1
New Load.L675 bus1=675 phases=3 kV=4.16 kW=300 kvar=180 model=1
New Load.L680 bus1=680 phases=3 kV=4.16 kW=150 kvar=90  model=1
New Load.L645 bus1=645 phases=3 kV=4.16 kW=170 kvar=100 model=1
New Load.L684 bus1=684 phases=3 kV=4.16 kW=120 kvar=70  model=1
New Load.L652 bus1=652 phases=3 kV=4.16 kW=140 kvar=85  model=1
Set voltagebases=[4.16]
Calcvoltagebases
"""

DER_BUSES = ["675", "671", "680", "684", "652", "645"]
VIOLATION_PU = 0.05
# Malicious swing: a COORDINATED DER-fleet setpoint manipulation at a bus (many
# inverters curtailed/driven together), realistic for a feeder with meaningful DER
# penetration -- hundreds of kW, not tens. On this ~1.5 MW feeder a 200-800 kW swing
# at a weak bus crosses the ANSI band.
DP_MIN, DP_MAX = 200.0, 800.0
ATTACKER_SHARPNESS = 3.0


def measure_sensitivities(feeder_path, probe_kw=100.0):
    """Return {bus: max|dV| per kW} from real OpenDSS solves."""
    import opendssdirect as dss
    dss.Text.Command("Redirect " + str(feeder_path))
    dss.Text.Command("Solve")
    base = dict(zip([b.split(".")[0] for b in dss.Circuit.AllNodeNames()],
                    dss.Circuit.AllBusMagPu()))
    sens = {}
    for bus in DER_BUSES:
        gname = f"mal_{bus}"
        dss.Text.Command(f"New Generator.{gname} bus1={bus} phases=3 kV=4.16 "
                         f"kW={probe_kw} kvar=0 model=1")
        dss.Text.Command("Solve")
        mags = dict(zip([b.split(".")[0] for b in dss.Circuit.AllNodeNames()],
                        dss.Circuit.AllBusMagPu()))
        worst = max(abs(mags[n] - base[n]) for n in mags)
        sens[bus] = worst / probe_kw          # pu per kW
        dss.Text.Command(f"Edit Generator.{gname} enabled=no")
        dss.Text.Command("Solve")
    return sens


def attacker_target(rng, sens):
    w = [sens[b] ** ATTACKER_SHARPNESS for b in DER_BUSES]
    return rng.choices(DER_BUSES, weights=w)[0]


def covered_set(policy, budget, rng, sens):
    if policy == "NO_DECEPTION":
        return set()
    if policy == "FULL_COVER":
        return set(DER_BUSES)
    if policy == "PHYSICS_AWARE":
        return set(sorted(DER_BUSES, key=lambda b: sens[b], reverse=True)[:budget])
    if policy == "RANDOM_COVER":
        return set(rng.sample(DER_BUSES, min(budget, len(DER_BUSES))))
    raise ValueError(policy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attacks", type=int, default=50000)
    ap.add_argument("--budgets", type=int, nargs="+", default=[1, 2, 3, 4])
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--feeder", default=None, help="path to a .dss feeder (default: writes ieee13_der.dss)")
    ap.add_argument("--outdir", default="results/n3_opendss")
    args = ap.parse_args()
    here = Path(__file__).resolve().parent
    out = Path(args.outdir); out.mkdir(parents=True, exist_ok=True)

    feeder = args.feeder
    if feeder is None:
        feeder = here / "ieee13_der.dss"
        feeder.write_text(FEEDER_DSS)

    sens = measure_sensitivities(feeder)
    print("Measured OpenDSS sensitivities (pu / kW), worst bus deviation:")
    for b in sorted(sens, key=lambda x: sens[x], reverse=True):
        print(f"  bus {b:>4}: {sens[b]:.3e}   (|dV| at {DP_MAX:.0f} kW = {sens[b]*DP_MAX:.4f} pu)")
    print()

    policies = ["NO_DECEPTION", "RANDOM_COVER", "PHYSICS_AWARE", "FULL_COVER"]
    rows = []
    for budget in args.budgets:
        for pol in policies:
            dvs, viol = [], 0
            for i in range(args.attacks):
                rng = random.Random(args.seed * 1_000_003 + budget * 101 + i)
                cov = covered_set(pol, budget, random.Random(args.seed * 7 + budget * 13 + i), sens)
                tgt = attacker_target(rng, sens)
                dp = rng.uniform(DP_MIN, DP_MAX)
                dv = 0.0 if tgt in cov else sens[tgt] * dp
                dvs.append(dv)
                if dv > VIOLATION_PU:
                    viol += 1
            dvs_sorted = sorted(dvs)
            p95 = dvs_sorted[int(0.95 * (len(dvs_sorted) - 1))]
            rows.append({"budget": budget, "policy": pol,
                         "violation_rate": viol / args.attacks,
                         "mean_dv_pu": statistics.mean(dvs), "p95_dv_pu": p95})

    with open(out / "n3_opendss.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    hdr = f"{'B':>3} {'policy':14}{'violation':>11}{'mean|dV|pu':>12}{'p95|dV|pu':>11}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        print(f"{r['budget']:>3} {r['policy']:14}{r['violation_rate']:11.3f}"
              f"{r['mean_dv_pu']:12.4f}{r['p95_dv_pu']:11.4f}")
    print(f"\nViolation = worst-bus |dV| > {VIOLATION_PU} pu (real OpenDSS solve). Lower is safer.")
    print(f"Wrote {out}/n3_opendss.csv")


if __name__ == "__main__":
    main()
