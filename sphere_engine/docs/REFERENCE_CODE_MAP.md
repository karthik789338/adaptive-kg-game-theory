# Reference-code map

Third-party repositories are references, not vendored dependencies in this clean codebase.

- CybORG — use its reset/step agent-environment organization, partial-observation discipline, and evaluation pattern as architectural references. MIT.
- Hierarchical-MARL — use the separation between a higher-level selector and lower-level defensive behaviors as a policy-organization reference. MIT.
- Learn-Red-Policy — use the observation-to-hidden-attacker-action prediction setup as a methodological reference. Do not copy code unless the repository's applicable license is confirmed.
- cage-4-submission — use its continuously updated observation-graph idea as a design reference for runtime graph mutations. GPL-2.0; do not copy source into this project unless license compatibility is explicitly accepted.
- dbn-sim-learning — use its attack-trace -> DBN parameterization -> held-out validation pipeline as the main H2 methodological reference. GPL-3.0 and PySMILE-dependent; this project reimplements a small transparent categorical DBN rather than copying its source.
- AttacKG — use technique-level cyber knowledge graph construction ideas and MITRE mapping as a reference. MIT.
- 2021 reachability graph analysis — use its attack-graph/Bayesian inference organization as a lightweight reference. MIT.
- GT-Engage — use its repeated incomplete-information game and Bayesian-belief-update organization as a conceptual reference. AGPL-3.0; no code copied here.
- Sicsp_ICS — use its ICS topology -> attack graph -> Bayesian attack graph workflow as an ICS-specific design reference. Treat bundled third-party components separately.
- DQN_grid — use its physical-grid reward/evaluation framing only as related implementation context; do not transfer absolute result values to EC-POMDG.
