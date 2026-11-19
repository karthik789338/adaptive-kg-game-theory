# Stage-conditioned EC-POMDG — engine patch, policy, and run plan

**Goal.** Give the defender a real decision at **every** kill-chain stage, so the
two currently-empty stages (RECON, ACCESS) stop being a pass-through in the game
tree. This is a clean extension of the deployed `ec_pomdg` engine and a new H1
variant; your locked base-game results stay as the baseline.

**Where it runs.** The H1 game is **in-process** (no live SPHERE traffic needed) —
it runs wherever `ec_pomdg` imports, i.e. your SPHERE XDC/defender node *or* your
`g6.4xlarge` EC2 with the repo checked out. Only the live IEC-104 campaign and the
OpenDSS physical probes need the testbed, and those results are unchanged.

---

## 1. Four new defender actions

Add these to `ec_pomdg.phase2a_game_contract.DefenderAction` (currently
`MONITOR, ACTIVATE_DECOY, REDIRECT, CONTAIN`):

| Action | Stage it serves | Cost | ICS analogue |
|---|---|---|---|
| `DECEPTIVE_SURFACE` | RECON | 1 | fake hosts / banners / honeytokens |
| `SESSION_CHALLENGE` | ACCESS | 1 | step-up auth / IEC-104 session throttle |
| `HONEY_POINTS` | DER_ENUM | 1 | decoy IEC-104 information objects (honey registers) |
| `SAFETY_INTERLOCK` | PHYSICAL | 2 | safety-instrumented trip / islanding |

Keep `ACTIVATE_DECOY`, `REDIRECT`, `CONTAIN` exactly as they are.

## 2. Transition / observation changes in `five_stage_ecpomdg_engine.py`

Implement the effects below inside the engine's `step()` transition. All
probabilities are suggested starting values calibrated to the existing kernel
(advance `a_C=0.68 / a_P=0.82`, redirect `p_r^C=0.72 / p_r^P=0.42`); keep them in
the config so they can be tuned.

- **`DECEPTIVE_SURFACE` (RECON) and `SESSION_CHALLENGE` (ACCESS).** On the turn the
  action is taken, multiply the attacker's stage-advance probability for that turn
  by `0.5` (the attacker dwells longer, giving the belief filter more evidence),
  and draw a **withdrawal** with probability `w_theta`:
  `w_C = 0.10` (RECON) / `0.08` (ACCESS) for CAUTIOUS,
  `w_P = 0.03` (RECON) / `0.02` (ACCESS) for PERSISTENT.
  A withdrawal terminates the episode in the existing `WITHDRAWN` outcome.
- **`HONEY_POINTS` (DER_ENUM).** Set an episode flag `honey=True`. While set, add
  `+0.20` to the redirect success probability at the control window (cap `0.95`).
  This is the lever that most helps against PERSISTENT (whose `p_r=0.42` is low).
  `HONEY_POINTS` does **not** itself arm the decoy; the policy still issues
  `ACTIVATE_DECOY`.
- **`SAFETY_INTERLOCK` (PHYSICAL).** If the attacker reaches the physical-impact
  resolution with the real target, the interlock prevents the physical effect with
  probability `0.90`, terminating in the **new** `CONTAINED_SAFE` outcome instead
  of `COMPROMISED_REAL`. (It does not divert — the real controller was reached, but
  no curtailment occurs.)
- **Unknown-action safety.** If an action member is present but the engine build
  does not handle it, treat it as `MONITOR` (so older runs never crash).

## 3. New terminal outcome and reward

Add `CONTAINED_SAFE` to the outcome enum / evaluation report, between a loss and a
win:

```
r_term(COMPROMISED_REAL) = -100
r_term(CONTAINED_SAFE)   =  -10      # real asset reached, physical impact prevented
r_term(DIVERTED_DECOY)   =  +12
r_term(WITHDRAWN)        =    0
```

Costs: `c(DECEPTIVE_SURFACE)=c(SESSION_CHALLENGE)=c(HONEY_POINTS)=1`,
`c(SAFETY_INTERLOCK)=2` (same scale as the existing `ACTIVATE_DECOY=1`,
`REDIRECT=1`, `CONTAIN=2`). The episode return is unchanged in form:
`R = r_term(y) - sum_t c(a_t^d)`.

## 4. The policy

`stage_conditioned_policy.py` (shipped alongside this file) is a drop-in
`StageConditionedDefenderPolicy` written against the **public** engine API
(`view.status.decoy_active`, `view.status.defense_budget_remaining`,
`view.episode_done`) and the deployed `BeliefConditionedMultiStageDefenderPolicy`,
which it reuses for the control/impact window. It tracks the stage by decision
index (matching the fixed attacker sequence in `run_experiments.py`) and reserves
budget for the arm+redirect bundle so early deception cannot starve the divert
lever.

## 5. Run it — extend `run_experiments.py`

Add the new policy to `H1_POLICIES` and run a **budget sweep** (the key result:
stage-conditioned defense is defense-in-depth and needs `B>=6`; the base policies
cannot spend the extra budget, so the comparison stays fair):

```python
from stage_conditioned_policy import StageConditionedDefenderPolicy
H1_POLICIES["STAGE_CONDITIONED"] = StageConditionedDefenderPolicy

# in run_episode(...), make budget a parameter:
#   engine = FiveStageECPOMDGEngine(seed=seed, attacker_profile=profile,
#                                   knowledge_mode=mode, budget=BUDGET, max_steps=10)
# and run the H1 sweep for BUDGET in (4, 6) and BOTH profiles (CAUTIOUS, PERSISTENT).
```

`run_experiments_extended.py` (shipped alongside) does exactly this and writes
`h1_stage_conditioned.csv` with diversion / withdrawn / contained_safe / compromise
/ mean-reward + 95% bootstrap CIs, for each policy x profile x budget.

## 6. Runbook (SPHERE XDC **or** g6.4xlarge EC2)

```bash
# on the node where ec_pomdg imports (SPHERE defender/XDC, or EC2 with the repo):
cd ~/ecpomdg_sphere/pipeline            # wherever run_experiments.py lives
cp /path/to/stage_conditioned_policy.py .
cp /path/to/run_experiments_extended.py .

# 1) apply the engine changes in sections 1-3 to ~/ecpomdg/ec_pomdg/
#    (phase2a_game_contract.py: 4 new actions; five_stage_ecpomdg_engine.py:
#     transition effects + CONTAINED_SAFE terminal + reward)

# 2) sanity: base policies must still reproduce Table I (unchanged)
PYTHONPATH="$HOME/ecpomdg" python3 run_experiments.py --seeds 200

# 3) the new experiment (both profiles, budget sweep)
PYTHONPATH="$HOME/ecpomdg" python3 run_experiments_extended.py --seeds 200 \
    --budgets 4 6 --outdir results/stage_conditioned
```

OpenDSS / physical probes are **not** needed for this — those results already
exist and don't change.

## 7. What to send back

`results/stage_conditioned/h1_stage_conditioned.csv`. I'll drop the real numbers
into the game tree and the paper (Section 4 methodology + a new H1-extension
results subsection — both drafted in `paper_additions.tex`), and finalize the
tree figure. Expected direction (from the mechanism, to be confirmed by your run):
compromise already ~0 for belief-adaptive, so the gains show up as **earlier
withdrawals** (RECON/ACCESS), **bounded damage** (CONTAINED_SAFE at impact), and
**higher reward headroom against PERSISTENT** — not as a compromise-rate drop.
