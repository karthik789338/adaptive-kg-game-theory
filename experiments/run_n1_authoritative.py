#!/usr/bin/env python3
"""N1 deception-aware attacker on the AUTHORITATIVE ec_pomdg engine
(FiveStageECPOMDGEngine + BeliefConditionedMultiStageDefenderPolicy -- the engine
that reproduces Table I). The 'fixed' condition is the untouched engine; 'aware'
subclasses it so a redirect is EVADED when the decoy was armed early (recon/access),
i.e. a predictable, fingerprintable decoy. Belief-adaptive arms on evidence and
keeps containment as a fallback, so it is not fingerprinted; a greedy early-arming
policy (stage-agnostic) is. Reuses pipeline/run_experiments.py's real policies and
ATTACK_SEQUENCE; both attacker profiles are threaded. Nothing in the engine is
modified.

Run on a node where the `ec_pomdg` package and `pipeline/run_experiments.py` are
importable (the SPHERE defender node / XDC):

    PYTHONPATH=$HOME/ecpomdg python3 run_n1_authoritative.py

Fixed-condition output reproduces Table I exactly (belief-adaptive 0.00 compromise,
reward +14.69 cautious / +2.51 persistent).
"""
import sys, os, csv, statistics
from collections import Counter
from pathlib import Path
HOME = os.path.expanduser('~')
sys.path.insert(0, HOME + '/ecpomdg')                      # ec_pomdg package
sys.path.insert(0, HOME + '/ecpomdg_sphere/pipeline')      # run_experiments module
import run_experiments as R
import ec_pomdg.five_stage_ecpomdg_engine as eng
from ec_pomdg.phase4b_stochastic_kernel import AttackerProfile
from ec_pomdg.multistage_attack_belief_runtime import KnowledgeMode

AttackStage = eng.AttackStage
EVADE = 0.85
EARLY = {AttackStage.RECONNAISSANCE, AttackStage.ACCESS}


class AwareEngine(eng.FiveStageECPOMDGEngine):
    """Deception-aware attacker: evades a redirect when the decoy was armed early."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._arm_stage = None

    def step(self, aa, da):
        pre = self.decoy_active
        ps = self.true_stage
        o = super().step(aa, da)
        if (not pre) and self.decoy_active and self._arm_stage is None:
            self._arm_stage = ps
        return o

    def _redirect_probability(self):
        p = super()._redirect_probability()
        if self._arm_stage in EARLY:
            p *= (1.0 - EVADE)
        return p


def run_ep(EngCls, policy, profile, mode, seed):
    e = EngCls(seed=seed, attacker_profile=profile, knowledge_mode=mode,
               budget=4, max_steps=10)
    for aa in R.ATTACK_SEQUENCE:
        v = e.current_defender_view()
        if getattr(v, 'episode_done', False):
            break
        e.step(aa, policy.decide(v))
    s = e.evaluation_report()['summary']
    return getattr(s['outcome'], 'value', s['outcome']), float(s['cumulative_defender_reward'])


def main():
    mode = KnowledgeMode.DYNAMIC_KG
    seeds = 200
    rows = []
    for mname, EngCls in [('fixed', eng.FiveStageECPOMDGEngine), ('aware', AwareEngine)]:
        for prof in [AttackerProfile.CAUTIOUS, AttackerProfile.PERSISTENT]:
            for pn, factory in R.H1_POLICIES.items():
                oc, rew = Counter(), []
                for sd in range(1, seeds + 1):
                    o, r = run_ep(EngCls, factory(), prof, mode, sd)
                    oc[o] += 1
                    rew.append(r)
                n = float(seeds)
                rows.append(dict(attacker=mname, profile=getattr(prof, 'value', str(prof)),
                    policy=pn, diversion=oc['DIVERTED_DECOY'] / n, withdrawn=oc['WITHDRAWN'] / n,
                    compromise=oc['COMPROMISED_REAL'] / n, mean_reward=statistics.mean(rew)))
    out = Path('results/n1_engine_authoritative').resolve()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'n1_engine.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('%-6s %-11s %-16s %6s %6s %6s %9s' % ('atk', 'profile', 'policy', 'div', 'wd', 'comp', 'reward'))
    for r in rows:
        print('%-6s %-11s %-16s %6.2f %6.2f %6.2f %9.2f' % (r['attacker'], r['profile'], r['policy'],
            r['diversion'], r['withdrawn'], r['compromise'], r['mean_reward']))
    print('wrote', out / 'n1_engine.csv')


if __name__ == '__main__':
    main()
