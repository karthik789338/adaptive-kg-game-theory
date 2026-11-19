#!/usr/bin/env python3
"""N3 cyber-physical coupling on the OFFICIAL IEEE 123-bus feeder (scaling study).
Perturbs each DER/load bus by a probe, measures the worst per-unit voltage deviation
with a real OpenDSS load flow, then runs the same physics-aware vs stage-blind cover
comparison as the IEEE-13 run (n3_opendss.py). Shows the physics-aware advantage
persists and widens as the feeder (and DER-bus count) scales up.

Requires the official IEEE-123 feeder in ./ieee123/ -- fetch it with
get_ieee123_feeder.sh, then:

    python3 n3_ieee123.py --attacks 20000 --budgets 2 4 8 16 --seed 11
"""
import opendssdirect as d
import random, statistics, csv, argparse
from pathlib import Path

VIOLATION_PU = 0.05
DP_MIN, DP_MAX = 200.0, 800.0      # coordinated DER-fleet setpoint swing (kW)
SHARP = 3.0
PROBE = 100.0


def solve_base():
    d.Text.Command('Compile (ieee123/IEEE123Master.dss)')
    d.Text.Command('Set MaxControlIter=30')
    d.Text.Command('New EnergyMeter.Feeder Line.L115 1')
    d.Text.Command('Solve')


def measure_sensitivities():
    solve_base()
    base = d.Circuit.AllBusMagPu()
    sens = {}
    i = d.Loads.First()
    while i:
        nm = d.Loads.Name()
        kw0 = d.Loads.kW()
        d.Loads.kW(kw0 + PROBE)
        d.Text.Command('Solve')
        mags = d.Circuit.AllBusMagPu()
        worst = max(abs(mags[k] - base[k]) for k in range(len(mags)))
        sens[nm] = worst / PROBE
        d.Loads.kW(kw0)
        i = d.Loads.Next()
    d.Text.Command('Solve')
    return sens


def target(rng, sens, buses):
    w = [sens[b] ** SHARP for b in buses]
    return rng.choices(buses, weights=w)[0]


def cover(pol, b, rng, sens, buses):
    if pol == 'NO_DECEPTION':
        return set()
    if pol == 'FULL_COVER':
        return set(buses)
    if pol == 'PHYSICS_AWARE':
        return set(sorted(buses, key=lambda x: sens[x], reverse=True)[:b])
    if pol == 'RANDOM_COVER':
        return set(rng.sample(buses, min(b, len(buses))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--attacks', type=int, default=20000)
    ap.add_argument('--budgets', type=int, nargs='+', default=[2, 4, 8, 16])
    ap.add_argument('--seed', type=int, default=11)
    ap.add_argument('--outdir', default='results/n3_ieee123')
    a = ap.parse_args()
    out = Path(a.outdir).resolve()          # absolute: OpenDSS Compile changes CWD
    out.mkdir(parents=True, exist_ok=True)
    sens = measure_sensitivities()
    buses = list(sens)
    print('DER/load buses:', len(buses))
    for b in sorted(buses, key=lambda x: sens[x], reverse=True)[:5]:
        print('  top bus %s  sens %.3e pu/kW  (|dV|@%dkW=%.4f)' % (b, sens[b], DP_MAX, sens[b] * DP_MAX))
    pols = ['NO_DECEPTION', 'RANDOM_COVER', 'PHYSICS_AWARE', 'FULL_COVER']
    rows = []
    for bud in a.budgets:
        for pol in pols:
            dvs, viol = [], 0
            for i in range(a.attacks):
                rng = random.Random(a.seed * 1_000_003 + bud * 101 + i)
                cov = cover(pol, bud, random.Random(a.seed * 7 + bud * 13 + i), sens, buses)
                tg = target(rng, sens, buses)
                dp = rng.uniform(DP_MIN, DP_MAX)
                dv = 0.0 if tg in cov else sens[tg] * dp
                dvs.append(dv)
                if dv > VIOLATION_PU:
                    viol += 1
            rows.append(dict(feeder='IEEE-123', n_der=len(buses), budget=bud, policy=pol,
                violation_rate=viol / a.attacks, mean_dv_pu=statistics.mean(dvs)))
    with open(out / 'n3_ieee123.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('%3s %-14s%11s%12s' % ('B', 'policy', 'violation', 'mean|dV|pu'))
    for r in rows:
        print('%3d %-14s%11.3f%12.4f' % (r['budget'], r['policy'], r['violation_rate'], r['mean_dv_pu']))
    print('wrote', out / 'n3_ieee123.csv')


if __name__ == '__main__':
    main()
