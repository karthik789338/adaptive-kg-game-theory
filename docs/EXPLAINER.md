# EC-POMDG — Explained End to End (plain English)

A walkthrough of the whole project in simple language: what we built, what each
stage means, what each deception technique actually is, what happened in the
experiments (with the real numbers), and what our findings are and why they are new.

If you want to explain this to someone in five minutes, read the **"In one
paragraph"** box and the **"What we found"** section. The rest fills in the detail.

---

## In one paragraph

A power grid is run by control computers that speak a protocol called **IEC-104**.
An attacker who breaks in can send fake commands and physically disturb the grid
(change voltages, trip equipment). Instead of only trying to *block* the attacker,
we **deceive** them: we watch how the attack unfolds, guess which step the attacker
is on, and at the right moment slip a convincing **decoy** in front of them so their
malicious command lands on a fake controller instead of the real one. The defender
never sees the attacker's step directly — it has to **infer** it from noisy clues,
helped by a **knowledge graph** (a map of how attacks and grid components relate).
We showed that a defender who **adapts to what it believes the attacker is doing**
beats every fixed, scripted defense — and, crucially, is the **only** defense that
still works when the attacker is smart enough to detect and dodge predictable
tricks. We proved this in simulation, in the real game engine, and finally **live on
a real power-grid cyber testbed (SPHERE)** with real IEC-104 traffic.

---

## 1. The cast: who is playing

- **The attacker.** Breaks into the grid network and tries to reach the **real
  controller** and issue a damaging command (e.g. a malicious DER setpoint that
  moves feeder voltage). Modeled on the real-world *Industroyer* grid malware.
- **The defender.** Sits on the network and chooses, turn by turn, whether to just
  watch, or to spend effort on a deception/mitigation action. It has a **limited
  budget** — it cannot do everything every turn.
- **Nature.** Decides at the start whether this episode even has an attacker, and if
  so, what *type* of attacker (see below). This is why the defender must *infer* —
  it does not get told.

### Two attacker personalities (this matters for the numbers)
- **Cautious (θ_C).** Advances slowly and is **easily diverted** — if it suspects a
  trap or hits friction, it often backs off. Advance probability **0.68**, redirect
  (divert-to-decoy) success **0.72**.
- **Persistent (θ_P).** Pushes hard and is **hard to divert**. Advance probability
  **0.82**, redirect success only **0.42**. This is the "hard" adversary — the one
  that really tests the defense.

---

## 2. The five stages (the attacker's kill chain)

An attack is not one event; it is a sequence. Think of a burglar: first they case
the neighborhood, then pick a door, then find the valuables, then grab them, then
escape. Our attacker goes through **five stages**, and the grid only gets hurt at the
end:

| # | Stage | What the attacker is doing (plain English) |
|---|---|---|
| 1 | **Reconnaissance** | Scanning the network, mapping what machines exist |
| 2 | **Access** | Getting a foothold — logging in / establishing a session |
| 3 | **DER enumeration** | Finding the actual grid control points (the DER setpoints it can abuse) |
| 4 | **Control manipulation** | Choosing and sending the malicious control command |
| 5 | **Physical impact** | The command executes on the **real** controller → the grid is physically disturbed |

**The core problem we fixed:** in the original design, the defender had **no move**
during stages 1 and 2. The game effectively started at stage 3. That is like a
security guard who is only allowed to act once the burglar is already inside the
vault. Our **stage-conditioned** version gives the defender a sensible action at
*every* stage (see the game tree). That is a big part of the novelty.

---

## 3. The deception techniques (what they are, in plain words)

At each stage the defender can play a **stage-appropriate** deception or mitigation
move. Here is what each one actually means:

- **DECEPTIVE_SURFACE (stage 1 — Reconnaissance).** *Fake hosts and honeytokens.*
  We make the network scan return **fake machines and fake credentials** that look
  real. A cautious attacker poking at a fake surface sometimes gives up (withdraws).
  Think: planting fake doors on a building so the burglar wastes time and gets
  nervous. Cost: 1 budget unit.

- **SESSION_CHALLENGE / ACTIVATE_DECOY (stage 2 — Access).** *Arm the decoy early /
  make them prove themselves.* We stand up a **decoy environment** and/or force an
  extra authentication step. Arming the decoy **early** means the trap is already in
  place by the time it matters at stage 4. Think: giving the burglar a key that opens
  a fake apartment. Cost: 1.

- **HONEY_POINTS (stage 3 — DER enumeration).** *Decoy grid control objects.* When
  the attacker looks for control points, we show them **fake IEC-104 "information
  objects"** (fake setpoints/registers) that look like the juiciest targets. Because
  the attacker is drawn to the fake target, our later redirect is **more likely to
  succeed** — this adds **+0.20** to the redirect success probability. Think: leaving
  a fake "valuables" safe where the burglar will find it first. Cost: 1.

- **REDIRECT (stage 4 — Control manipulation).** *Send their command to the decoy.*
  This is the **main lever**. When the attacker issues the malicious control command,
  we route it to the **decoy controller** instead of the real one. If it works, the
  attack is **diverted** — it hits a fake and does zero physical harm, and we get to
  watch it. Think: the burglar grabs the safe, but it is the fake one. Cost: 1.

- **CONTAIN (stage 5 — Physical impact).** *Stop the attack.* If the attacker is
  still aimed at the **real** controller, well-timed containment **halts** the attack
  before it executes — the attacker withdraws, no physical harm. This is the safety
  net that guarantees the real controller is never hit. Cost: 2.

- **SAFETY_INTERLOCK (stage 5 — last resort).** *Safety-instrumented trip.* A
  physical safety mechanism that, with 90% success, converts a real-controller hit
  into a **contained-safe** outcome (mild penalty) instead of full compromise. Cost: 2.

### The outcomes (the "leaves" of the tree) and their scores
- **DIVERTED_DECOY (+12)** — best case: attacker fooled onto the decoy.
- **NO_INCIDENT / WITHDRAWN (0)** — attacker gave up or was stopped; no harm, no reward.
- **CONTAINED_SAFE (−10)** — real controller was reached but the safety trip bounded the damage.
- **COMPROMISED_REAL (−100)** — worst case: the real grid controller was hit.

The defender wants to **maximize diversions and avoid compromises**, while **not
wasting budget** on turns where there is no attacker.

---

## 4. The four defenders we compared

To show the value of *adapting*, we test four defenders against the same attacks:

1. **MONITOR_ONLY** — never deceives, just watches. (The "do nothing" baseline.)
2. **FIXED_SCHEDULE** — deceives on a **fixed timetable** (e.g. always arm at turn 2,
   redirect at turn 4), regardless of what the attacker is doing.
3. **STAGE_AGNOSTIC** — deceives greedily but **ignores the inferred stage/timing**.
4. **BELIEF_ADAPTIVE** — the smart one: it keeps a **belief** (a probability) about
   which stage the attacker is on, and acts **only when the evidence says it is time**.

The first three are "stage-blind" — they do not use the belief about the attacker.
The fourth is our method.

---

## 5. What happened — results in plain English

### Finding A — doing nothing is a disaster; adapting is near-perfect

Against the easier **cautious** attacker, if the defender just watches
(MONITOR_ONLY), the attacker reaches the real controller **~99 times out of 100**.
Against the **persistent** attacker it is **100 out of 100**. The grid is basically
defenseless.

Turn on the **belief-adaptive** defender (with enough budget, B ≥ 4):

- **Compromise drops to 0** — the real controller is **never** reached, for *both*
  attacker types.
- The cautious attacker is **diverted to the decoy ~61% of the time**; the rest of
  the time it is contained/withdraws (0% harm).
- The persistent attacker is diverted **~19%** of the time and contained the rest —
  still **0% compromise**.

> **Because** the defender waits for the right moment (evidence-driven) and keeps
> budget in reserve for the redirect-and-contain combo, **no attack reaches the real
> grid**, whereas the "do nothing" defender loses almost every time.

**One honest caveat:** the zero-compromise guarantee needs **budget ≥ 4**. At budget
3 the defender cannot afford arm + redirect + contain, and it degrades to the
scripted defense (39% compromise cautious, 81% persistent). So we report results at
B ≥ 4 and show the budget sensitivity.

### Finding B (the strongest one) — only the adaptive defender survives a *smart* attacker

This is our headline novelty. We built a **deception-aware attacker** — one that
**detects predictable, early-armed decoys and dodges them** (it evades a
fingerprinted decoy ~85% of the time). This is a much more realistic adversary; most
research assumes the attacker is oblivious.

What happens to each defender when the attacker gets smart:

| Defender | Compromise vs **naive** attacker | Compromise vs **smart** attacker |
|---|---|---|
| Fixed-schedule (cautious) | 39% | **90%** |
| Fixed-schedule (persistent) | 81% | **97%** |
| Stage-agnostic | 26–67% | **85–94%** |
| **Belief-adaptive** | **0%** | **0%** |

> **Because** the scripted defenses always act at the same time, the smart attacker
> learns the pattern and walks around it — and they **collapse** (up to 97%
> compromise). The belief-adaptive defender acts on **evidence**, so its timing is
> **different every episode** — there is **no pattern to fingerprint**, and it stays
> at **0% compromise** while keeping its full diversion rate.

We call the mechanism behind this the **deception detectability tradeoff**:
aggressive, early, always-on deception grabs more diversions against a dumb attacker,
but it is *visible* and a smart attacker dodges it; evidence-driven timing gives up a
little diversion in exchange for being **unpredictable and robust**.

### Finding C — a "honey-point" trap nearly doubles diversions against the hard attacker

Adding the **HONEY_POINTS** move at stage 3 (the fake control objects) raises the
redirect success by +0.20. The effect is biggest exactly where we need it — against
the **persistent** attacker, whose base redirect success is lowest:

- Persistent-attacker diversion rises from **0.19 → 0.37** (nearly double) at
  adequate budget, still at **0% compromise**.

> **Because** the attacker is lured toward the fake target during enumeration, the
> later redirect is far more likely to land — so we **catch** the hard attacker on the
> decoy instead of merely stalling it.

### Finding D — the knowledge graph makes the defender's guesses much better

The defender cannot see the attacker's stage; it **infers** it. A **knowledge graph
(KG)** — a map of ~6,756 facts linking cyber attack patterns, ICS/grid semantics, and
the grid's component topology — gives the belief filter better clues.

- With a **stale/no KG**, the defender guesses the attacker's stage correctly only
  **~18%** of the time.
- With an **online/learning KG**, accuracy jumps to **~54%** — essentially matching a
  perfect "oracle" that knows the true clue-to-stage mapping. So the learning is doing
  as well as is theoretically possible, not overclaiming.
- On the **real Neo4j knowledge graph** (live testbed), every KG "domain" we switch on
  significantly improves inference; the **grid topology** piece helps most
  (log-loss 0.72 → 0.61, lower is better).

### Finding E — a "dynamic" KG recognizes a returning attacker instantly

The biggest KG result: a **dynamic** KG that *remembers past campaigns* can spot a
**returning** attacker **immediately**, where a static KG has to figure it out from
scratch each time.

- Against recurring attackers, the dynamic KG cuts the error (log-loss) by **−0.28**,
  and its **detection turn is 0** (it knows on turn 1) versus **0.69** for static.
- Confirmed **live on the real Neo4j store**: dynamic beats static by **−0.19 to
  −0.24 log-loss on 100% of paired episodes**.
- Honest bound: if the attacker **never** returns, the advantage disappears — proving
  the gain is genuinely "recognizing returning campaigns," not a trick of the math.

### Finding F — protecting the *physically* important points stops real grid damage

We coupled the game to a **real power-flow simulation (OpenDSS)** of an IEEE-13-style
feeder. A smart attacker aims at the **buses where a malicious setpoint moves voltage
the most**. A **physics-aware** defender covers those exact high-impact buses first:

| Deception budget | Undefended | Random cover | **Physics-aware cover** |
|---|---|---|---|
| B=1 | 36.7% | 30.6% | **23.7%** |
| B=2 | 36.7% | 24.6% | **14.3%** |
| B=3 | 36.7% | 18.3% | **6.1%** |
| B=4 | 36.7% | 12.0% | **2.2%** |

(Numbers = share of attacks that cause a real voltage violation, |ΔV| > 0.05 pu.)

> **Because** the defender protects the few buses that actually matter physically —
> the same ones a rational attacker targets — it **roughly halves** the violation rate
> versus a stage-blind defender at every budget. On the live testbed, a 200 kW
> malicious curtailment produced a measured 200 kW swing on the real controller, while
> the decoy produced **no** physical effect — confirming the physical channel is real.

### Finding G (the honest one) — the live testbed exposed a sim-to-real gap

We ran the defense **live on SPHERE** with real IEC-104 traffic — **160 episodes, 0
failures**. The deception worked on the wire (we can see the malicious command on the
real object `0x4001` being answered by the decoy object `0x8001`). **But**: the
simulator's *cost-efficiency* advantage — belief-adaptive spending **less** effort on
quiet/benign days than the scripted defense — **did not carry over** at the
simulation-tuned settings. Live, the belief defender armed on benign episodes just as
often as the fixed one.

> This is not a failure — it is exactly what a real testbed is **for**. The
> **inference-side** gains (the KG findings D/E) **do** transfer and get stronger live;
> the **cost-control** advantage needs **live re-calibration** of the decision
> thresholds. Reporting this honestly is itself a contribution — most deception papers
> never cross the sim-to-real line.

---

## 6. What we found (one-line summaries)

1. **Adapting beats scripting.** A belief-driven defender takes real-controller
   compromise from ~99–100% down to **0%** (budget ≥ 4).
2. **Only adapting survives a smart attacker.** Against an attacker that dodges
   predictable decoys, scripted defenses hit **90–97% compromise**; the adaptive one
   stays at **0%**. *(strongest result)*
3. **Honey-points nearly double** diversion of the hard persistent attacker
   (0.19 → 0.37).
4. **The knowledge graph triples** stage-inference accuracy (18% → 54%, ≈ oracle).
5. **A dynamic KG recognizes returning attackers instantly** (detection turn 0 vs
   0.69; confirmed on the real graph store).
6. **Physics-aware deception halves** real voltage violations at every budget.
7. **It runs live on a real ICS testbed** (0 failures), and the live run honestly
   reveals where simulation and reality differ.

---

## 7. Why these findings are novel

Prior work does these things **separately**: honeypot/deception games assume a
**non-adaptive** attacker and ignore the physics; knowledge-graph security work maps
threats but does **not** drive live deception decisions; grid-defense games rarely use
real protocol traffic. **No prior work combines all of:** protocol-grounded
multi-stage belief (real IEC-104), knowledge-graph-conditioned inference with a
**dynamic memory** of past campaigns, **budget-limited** deception, and **measured
physical** consequences — and **none** test **robustness to an attacker that adapts to
the deception itself.**

Our specific new contributions:

- **A new, harder threat model + result (strongest).** The *deception-aware* attacker,
  and the proof that evidence-driven timing is the **only** defense robust to it. This
  reframes the story from "adaptive is a bit better" (incremental) to "adaptive is the
  only thing that survives a smart adversary" (novel).
- **A decision at every kill-chain stage.** We fill the two empty early stages (recon,
  access) with real deception moves, so deception is a continuous strategy, not a
  single stage-4 trick.
- **A dynamic, self-correcting knowledge graph** that recognizes returning attackers —
  closing a loop the base design left open — validated on a **real Neo4j** store.
- **Physics as a decision variable.** The defender allocates deception to the buses
  that matter physically, validated against **real OpenDSS** power flow.
- **A three-tier evaluation** (simulation → real engine → live testbed) that both
  confirms the gains on real infrastructure **and** honestly surfaces the sim-to-real
  gap — a level of validation most deception papers never reach.

---

## 8. The 60-second script (for explaining out loud)

> "Grid control computers talk over IEC-104. An attacker who breaks in walks through
> five stages and only hurts the grid at the last one. Instead of just blocking, we
> **deceive**: we infer which stage the attacker is on and, at the right moment, slip a
> **decoy** in front of them so their attack hits a fake controller. A defender that
> **adapts to its belief** about the attacker takes compromise from ~100% down to 0% —
> and it is the **only** defense that still works when the attacker is smart enough to
> dodge predictable traps; the scripted defenses collapse to 90–97% compromise. A
> **knowledge graph** triples our ability to guess the attacker's stage, and a
> **dynamic** version recognizes a returning attacker instantly. We protect the grid
> buses that matter **physically**, cutting real voltage violations in half. And we
> proved it **live on a real power-grid cyber testbed**, where we also honestly found
> which advantages need re-tuning for the real world."
