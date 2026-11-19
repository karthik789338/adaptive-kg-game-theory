# EC-POMDG live-engine experiments

Engine: frozen five-stage ec_pomdg (SPHERE defender). H1 episodes/policy: 200.


## H1 - belief-conditioned deception vs stage-blind baselines (DYNAMIC_KG)

| policy | diversion | withdrawn | compromise | mean reward |
|---|---|---|---|---|
| MONITOR_ONLY | 0.00 | 0.00 | 1.00 | -100.00 |
| FIXED_SCHEDULE | 0.61 | 0.00 | 0.39 | -25.48 |
| STAGE_AGNOSTIC | 0.82 | 0.00 | 0.18 | -1.40 |
| BELIEF_ADAPTIVE | 0.61 | 0.39 | 0.00 | +14.69 |

H1: **BELIEF_ADAPTIVE** best (reward +14.69); **MONITOR_ONLY** worst (-100.00).


## H2a - static KG improves attacker-stage inference over telemetry-only (first encounter: NO_KG vs STATIC_KG)

| mode | RECONNAISSANCE | ACCESS | DER_ENUMERATION | CONTROL_MANIPULATION | PHYSICAL_IMPACT | mean |
|---|---|---|---|---|---|---|
| NO_KG | 0.835 | 0.499 | 0.373 | 0.420 | 0.434 | 0.512 |
| STATIC_KG | 0.901 | 0.614 | 0.558 | 0.655 | 0.687 | 0.683 |

H2a: STATIC_KG > NO_KG at every stage -- KG context improves inference; telemetry-only is weakest.


## H2b - dynamic KG beats static on attacks SEEN A SECOND TIME (STATIC_KG vs DYNAMIC_KG)

| mode | encounter_1 | encounter_2 | encounter_3 | gain |
|---|---|---|---|---|
| STATIC_KG | 0.6828 | 0.6828 | 0.6828 | +0.0000 |
| DYNAMIC_KG | 0.7425 | 0.7597 | 0.7747 | +0.0322 |

H2b: DYNAMIC_KG gains confidence on replay (episode-overlay memory); STATIC_KG is flat.
