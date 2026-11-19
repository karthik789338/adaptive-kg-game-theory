# EC-POMDG — positioning against related work

Comparison of EC-POMDG against the uploaded references. Claims about other
papers are taken from their abstracts/methods as read; where a paper was only
skimmed at the abstract level this is noted. Numbers for other systems are *their
own reported numbers on their own setups* — they are context, not a same-dataset
head-to-head (definitions differ; see "Apples-to-apples" below).

## 1. Capability matrix — what each method combines

| work | model class | hidden-state belief | deception (decoy/redirect) | KG / ATT&CK-grounded | dynamic / temporal update | cyber-physical ICS | live testbed |
|---|---|---|---|---|---|---|---|
| **EC-POMDG (ours)** | partially-obs. Markov **game** | ✅ 5-stage posterior | ✅ decoy + redirect + contain | ✅ 3 KGs (ATT&CK/CAPEC/CWE/KEV, ICS, topology) in Neo4j | ✅ episode overlay + campaign memory | ✅ IEEE-13 + IEC-104 | ✅ SPHERE (12 nodes) |
| Li et al., IJEPES 2026 | multistage sequential **game**, incomplete obs. | ✅ attack-intent / hidden state | ❌ (protection, reconfig, recovery) | ❌ multi-source feedback | ✅ feedback learning | ✅ isolated power grid | ✅ hardware-in-the-loop |
| Miehling et al., TIFS 2018 | **POMDP** | ✅ attacker state + type | ❌ (block exploits) | dependency/attack graph (not ATT&CK) | ❌ | ❌ general cyber net | illustrative example |
| Cerotti et al., IEEE Access 2025 | **DBN** | ✅ inference posterior | ❌ | ✅ attack graph + MITRE ATT&CK → DBN | time-driven DBN (temporal inference) | ✅ power system | simulated scenarios |
| Horák et al., Comp&Sec 2019 | partially-obs. stochastic **game** | ✅ | ✅ honeypot + redirect | ❌ | ✅ dynamic honeypot reallocation | ❌ general network | experimental eval |
| Feng et al., IET CPS 2020 *(abstract)* | **stochastic game** | — | ❌ | ❌ | — | ✅ power grid, coordinated attacks | simulation |
| Russo et al., ITASEC 2026 | honeypot (LLM + RAG) | ❌ | ✅ high-interaction ICS honeypot | RAG over process/domain data | ❌ | ✅ ICS | emulation |
| Rowe et al., HICSS 2020 | honeypot (Conpot/GridPot) | ❌ | ✅ ICS honeypot | ❌ | ❌ | ✅ electric grid | live traffic |
| Arifin et al., IEEE Access 2024 | ML IDS classifiers | ❌ | ❌ | ❌ | ❌ | ✅ IEC-104 SCADA | hybrid virtual-physical |
| Dynamic Attack-Path Pred. *(title/abstract)* | prob. attack-path prediction | path belief | ❌ | attack graph | ✅ dynamic prediction | ✅ ICPS | — |

**Takeaway.** No prior work in this set combines all five of EC-POMDG's axes:
a partially-observable **game** with a **stage belief**, **deception** actions, an
explicit **cyber-physical KG** grounding, and a **temporally-updated** KG. The
closest single paper is **Li 2026** (game + belief + dynamic + power-grid CPS),
which lacks the KG grounding and the decoy/redirect deception; the closest
inference paper is **Cerotti 2025** (DBN + ATT&CK), which lacks the game and the
deception/response layer.

## 2. Metric mapping — our results vs. what comparable work reports

Comparable work is benchmarked on **outcome / operational** or **detection**
metrics, not stage-inference log-loss. Our strongest, cleanest results live at the
same outcome level.

| axis | representative prior metric | EC-POMDG result |
|---|---|---|
| defense vs. no-defense / static | Li 2026: dynamic beats no-defense/static on operational indicators | H1: BELIEF_ADAPTIVE **0% compromise, +14.69 reward** vs MONITOR-ONLY **100% / −100**, fixed/greedy 18–39% compromise |
| attacker diversion via deception | Horák 2019 / Rowe 2020: engagement/diversion | H1: decoy **diversion rate 0.61**, plus withdrawn 0.39 |
| multi-stage attack detection | Cerotti 2025: DBN accuracy, KL-divergence; Arifin 2024: DT/RF **93.66%** flat detection | H2: STAGE inference, KG improves true-stage confidence NO_KG 0.512 → STATIC 0.683 (idealized trail); 8-mask ablation isolates **ICS KG** as the contributor |
| temporal / repeat-attack gain | Li 2026: "evolving attack intent"; Dynamic Attack-Path: dynamic prediction | H2b seen-twice: DYNAMIC +0.032 over repeats, STATIC flat (**Phase 3 will strengthen this with live record→replay**) |
| decoy realism | Russo 2026 / Rowe 2020: believable ICS honeypot | decoy serves physically-plausible IEEE-13 bus-675 responses via the frozen voltage model + validation; **topology KG proves decoy has no physical-control edge** |

## 3. Apples-to-apples caveats (so the comparison is honest)

- **Different datasets/testbeds.** Arifin 2024 uses their own IEC-104 capture with
  network-level attacks (scans/floods); our attacks are a staged ICS progression
  (Industroyer-style IEC-104). Their 93.66% is flat attack/no-attack-class
  detection, not 5-stage inference — cite as protocol-matched context, not a
  same-task number.
- **Different defense action sets.** Li 2026 and Miehling 2018 defend by
  blocking/reconfiguration/recovery; we add **deception** (decoy + redirect). Horák
  2019 and the honeypot papers use deception but no physical-stage belief.
- **Our ablation is information-matched.** The 8-mask KG ablation's small margins
  come from its own negative control (graph gives no advantage over an
  information-matched flat baseline); the KG's large effect is at the
  decision/outcome level (H1), which is where the sibling papers also report.

## 4. How to use this in the paper

- **Related work / positioning:** the capability matrix (Table 1) is the one-figure
  argument for novelty — EC-POMDG is the only cell with game + belief + deception +
  cyber-physical KG + temporal update.
- **Baseline comparison:** frame H1 exactly as Li 2026 does (no-defense / static /
  dynamic), adding our deception + KG; cite Cerotti 2025 and Miehling 2018 as the
  inference/POMDP ancestors; cite Horák 2019, Russo 2026, Rowe 2020 for deception.
- **Phase 3 motivation:** the dynamic record→replay experiment is what distinguishes
  us from the static-KG inference papers and realizes Li 2026's "evolving intent"
  idea with an explicit, queryable temporal KG.

### References (as uploaded)
- Li, Lv, Wang, Chen, Cheng, Luo. *Feedback-Learning-Based dynamic defense for isolated power grid CPS under coordinated cyber-physical attacks.* Int. J. Electrical Power & Energy Systems 181 (2026).
- Cerotti, Savarro, Codetta Raiteri, Dondossola, Egidi, Franceschinis, Portinale, Terruggia. *Dynamic Bayesian Networks for the Detection and Analysis of Cyber Attacks to Power Systems.* IEEE Access, 2025.
- Miehling, Rasouli, Teneketzis. *A POMDP Approach to the Dynamic Defense of Large-Scale Cyber Networks.* IEEE TIFS 13(10), 2018.
- Horák, Bošanský, Tomášek, Kiekintveld, Kamhoua. *Optimizing honeypot strategies against dynamic lateral movement using partially observable stochastic games.* Computers & Security 87 (2019).
- Feng et al. *Stochastic games for power grid coordinated defence against coordinated attacks.* IET Cyber-Physical Systems 2020.
- Russo, Marasco, Colajanni. *A Hybrid Honeypot for Cyber Detection and Deception in Industrial Control Systems.* ITASEC/SERICS 2026.
- Rowe, Nguyen, Kendrick, Rucker, Hyun, Brown. *Creating Effective Industrial-Control-System Honeypots.* HICSS-53, 2020.
- Arifin, Stiawan, Suprapto, Susanto, Idris, Shenify, Budiarto. *A Novel Dataset for Experimentation With IDS in SCADA Networks Using IEC 60870-5-104.* IEEE Access, 2024.
- *Dynamic Attack Path Prediction and Visualization for Industrial Cyber-Physical Systems Under Cyber Attacks.* (uploaded)
- *HoneyV.* IEEE/IFIP NOMS 2018.
