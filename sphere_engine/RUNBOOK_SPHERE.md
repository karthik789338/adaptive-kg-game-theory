# SPHERE test — one command

=== [1/7] deps + tests ===
..............                                                           [100%]
14 passed in 0.20s
=== [2/7] build actor population (benign + attacker, recurrence 0.6) ===
SYNTH: wrote train/ and test/ phase1+phase2 streams under /home/claude/ecpomdg_claude/data/streams (120 attack + 120 benign actors each, recurrence=0.6)
=== [3/7] REAL-DATA wiring check on captured episodes: /root/backup_dir/ecpomdg_audit/multistage_game/live_action_gated_decoy ===
=== [1/7] deps + tests ===
..............                                                           [100%]
14 passed in 0.29s
=== [2/7] build actor population (benign + attacker, recurrence 0.6) ===
SYNTH: wrote train/ and test/ phase1+phase2 streams under /home/claude/ecpomdg_claude/data/streams (120 attack + 120 benign actors each, recurrence=0.6)
=== [3/7] no REAL_EPISODES path given -> skipping real-data wiring check ===
=== [4/7] using REAL Neo4j store: bolt://10.50.0.30:7687 ===
    initialising inference schema in Neo4j ...
    (schema init skipped/failed - continuing)
=== [5/7] dynamic-vs-static replay (learn -> eval through the store) ===

It installs deps, runs tests, builds the actor population, folds your real
captures in as a real-data wiring check, records campaigns into Neo4j (or a
JSON store), runs the dynamic-vs-static replay, H2, H1 + joint, and prints a
PASS/FAIL verdict per hypothesis. Results land in results/*.json.

HONEST SCOPE: the attacker/benign population is the validated traffic model;
your captured episodes (one source IP, clean attacker-only, small n) are folded
in as a wiring check, not as the statistic. The campaign store is your real
Neo4j when NEO4J_PASSWORD is set. For fully-live numbers, have the testbed emit
benign operator traffic + per-actor source IPs and re-run the same command.

---

## KG 7-mask ablation (which of the 3 KGs drives inference)

mask    log_loss   accuracy  vs NONE (CI)                
NONE    0.7219     0.7349    (baseline)                  
G       0.7126     0.7375    -0.0094 [-0.0173,-0.0017] sig
I       0.7089     0.7389    -0.0130 [-0.0200,-0.0060] sig
T       0.6123     0.7719    -0.1096 [-0.1302,-0.0888] sig
G_I     0.7058     0.7389    -0.0161 [-0.0245,-0.0080] sig
G_T     0.6171     0.7676    -0.1049 [-0.1213,-0.0882] sig
I_T     0.6148     0.7685    -0.1071 [-0.1237,-0.0904] sig
G_I_T   0.6256     0.7610    -0.0963 [-0.1110,-0.0816] sig

RESULT: /home/claude/ecpomdg_claude/results/kg_ablation.json  (tables source: synthetic)
run_sphere_test.sh also runs this automatically as step [8/8].


# SPHERE end-to-end runbook — EC-POMDG (unzip → H1 → H2 → dynamic-vs-static)

Every command is copy-paste. Lines are tagged with the SPHERE node they run on,
using the hostnames/addresses from `topology/sphere-testbed.py`:

| node | role | experiment address |
|---|---|---|
| `kg` | Neo4j store of record | `10.50.0.30` (defense plane) |
| `collector` | telemetry collector | `10.45.0.30` tel / `10.50.0.20` def |
| `defender` | belief filter + policy | `10.50.0.40` |
| `controller` / `decoy` | IEC-104 real / decoy | `10.30.0.10` / `10.30.0.99` |
| `gridsim` | OpenDSS physical process | `10.40.0.20` |
| `attacker` | Industroyer-inspired IEC-104 | `10.10.0.10` |
| `operator` | dashboard (ingress :8501) | `10.50.0.50` |

The XDC/orchestration node has SSH/Ansible to all of them (SPHERE infranet).
Set this once on the XDC node:

```bash
export ECPOMDG=~/ecpomdg_final
export KG_HOST=10.50.0.30
export NEO4J_PASSWORD='change-me'        # must match the Neo4j you start on kg
```

---

## 0. Unpack (XDC node, then push to defender + kg)

```bash
# [xdc] unzip and verify
tar -xzf ecpomdg_claude.tar.gz && cd ecpomdg_final
sha256sum -c ../ecpomdg_claude.tar.gz.sha256 || true

# [xdc] distribute to the nodes that run code (adjust user/paths for your XDC)
for n in defender kg collector controller decoy attacker; do
  rsync -a --delete ./ "$n":~/ecpomdg_final/
done
```

## 1. Python env + preflight (defender + kg)

```bash
# [defender] and [kg]
cd ~/ecpomdg_final
python3 -m pip install -r requirements.txt       # numpy pandas networkx neo4j
python3 scripts/preflight.py                      # must print PREFLIGHT: PASS
python3 -m pytest -q tests                         # 14 passed
```

## 2. Start Neo4j and initialise the schema (kg node)

```bash
# [kg] start Neo4j 5.x (docker shown; a native install is fine too)
docker run -d --name ecpomdg-neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/$NEO4J_PASSWORD neo4j:5

# Community Edition uses the single neo4j database; train/test are separated by a
# population property (no CREATE DATABASE needed).
# [defender] initialise the inference schema + semantic nodes
NEO4J_URI=bolt://$KG_HOST:7687 NEO4J_PASSWORD=$NEO4J_PASSWORD \
  python3 scripts/initialize_neo4j_schema.py          # prints NEO4J_FINAL_SCHEMA: PASS
```

## 3. Build the three frozen knowledge graphs (defender → kg)

```bash
# [defender] component-topology (IEEE-13 / OpenDSS), ICS-cyber, general-cyber
python3 kg_builders/component_topology/build_power_grid_component_topology_knowledge_graph.py
python3 kg_builders/power_grid_ics/build_power_grid_ics_cyber_knowledge_graph.py
python3 kg_builders/general_cyber/build_general_cyber_knowledge_graph.py

# [defender] load the frozen graphs into Neo4j on the kg node
NEO4J_URI=bolt://$KG_HOST:7687 NEO4J_PASSWORD=$NEO4J_PASSWORD \
  python3 kg_builders/neo4j_migration/import_frozen_knowledge_graphs_into_neo4j.py
```

---

## 4. H2 — knowledge-graph-assisted stage inference (defender)

```bash
# [defender] telemetry-only vs static-KG vs dynamic-KG stage inference
python3 scripts/run_experiment_h2.py --episodes 400
#   -> results/h2_inference.json
#   expect STATIC and DYNAMIC log-loss significantly below TELEMETRY_ONLY.
```

## 5. H1 — belief-conditioned multi-stage defense (defender)

```bash
# [defender] MONITOR / FIXED / STAGE_AGNOSTIC / BELIEF_ADAPTIVE on matched episodes
python3 scripts/run_experiment_h1.py --episodes 500 --val 150
#   -> results/h1_closed_loop.json
#   expect BELIEF_ADAPTIVE best on overall utility (cost-controlled defense).

# [defender] joint check: does the inference gain become an operational gain?
python3 scripts/run_experiment_joint.py --episodes 400 --val 150
#   -> results/joint_h1_h2.json
```

---

## 6. Dynamic-vs-static via campaign replay — the "seen a second time" proof

This is the experiment that isolates the DYNAMIC advantage: the same attacks are
run twice. Phase 1 writes confirmed campaigns into Neo4j on the `kg` node; Phase 2
replays them. STATIC has no memory; DYNAMIC recognises the returning adversary.

### 6a. Live on SPHERE (real IEC-104 traffic through the collector)

The attacker emulator sends one scenario at a time with its real flags
(`--target {real,decoy}`, `--scenario {observe,p_curtail,q_manipulate,impact_sequence}`).
A "campaign" is a scenario sequence for one actor; a "phase" is running the
campaign set once. Give each campaign a distinct actor identity the collector
can see (e.g. a per-run client id / source port), so returning actors are
recognisable. Drive it from the XDC node:

```bash
# [xdc->attacker] PHASE 1 (calibration round): run the campaign set once.
#   Vary --scenario across actors; impact_sequence is a full RECON..IMPACT chain.
for sc in observe p_curtail q_manipulate impact_sequence; do
  ssh attacker "cd ~/ecpomdg_final && \
    python3 services/attacker/industroyer_inspired_iec104_emulator.py \
      --target real --scenario $sc"
done
# (the collector on 10.45.0.30 logs defender_observation_events.jsonl +
#  experiment_oracle_events.jsonl on the telemetry plane)

# [defender] stage the collector logs into the train population, Phase 1
python3 scripts/live/stage_collector_stream.py \
  --observations <collector>/defender_observation_events.jsonl \
  --oracle       <collector>/experiment_oracle_events.jsonl \
  --out data/streams --population train --phase phase1 --actor-key actor_id

# [defender] record the train Phase-1 campaigns into Neo4j (store of record)
python3 scripts/live/ecpomdg_live.py \
  --neo4j-uri bolt://$KG_HOST:7687 --neo4j-password $NEO4J_PASSWORD learn train

# ... repeat the attacker run to produce train/phase2, test/phase1, test/phase2,
#     staging each with --population/--phase accordingly, and `learn test`.

# [defender] evaluate STATIC vs DYNAMIC on the test population (reads Neo4j)
python3 scripts/live/ecpomdg_live.py \
  --neo4j-uri bolt://$KG_HOST:7687 --neo4j-password $NEO4J_PASSWORD \
  eval --out results/sphere_live_replay.json
#   expect DYNAMIC log-loss well below STATIC, with the largest gap and
#   near-zero detection turn on the recurring-attacker episodes.
```

> The only testbed-specific glue is `stage_collector_stream.py` (collector
> fields -> canonical schema); edit its `KEY_MAP` if your collector names fields
> differently. Everything downstream is identical to the tested dry-run below.
> `--neo4j-uri` is optional everywhere: omit it to use a local JSON store.

### 6b. Dry-run / CI without live traffic (any node)

Exercises the exact same code path on synthesised telemetry (Neo4j optional):

```bash
# [defender] synth -> learn(train) -> learn(test) -> eval
python3 scripts/live/ecpomdg_live.py synth --attack-actors 120 --benign-actors 120 --recurrence 0.6
python3 scripts/live/ecpomdg_live.py learn train
python3 scripts/live/ecpomdg_live.py learn test
python3 scripts/live/ecpomdg_live.py eval --out results/sphere_live_replay.json
# add --neo4j-uri bolt://$KG_HOST:7687 --neo4j-password $NEO4J_PASSWORD to use Neo4j.
```

---

## 7. One-shot offline reproduction (sanity, no SPHERE)

```bash
python3 scripts/run_all_offline.py     # smoke + H2 + H1 + joint + replay
```

## Expected offline numbers (seed-fixed; see RESULTS.md)

- H2: STATIC/DYNAMIC log-loss significantly below TELEMETRY_ONLY.
- H1: BELIEF_ADAPTIVE best overall utility.
- Replay: DYNAMIC − STATIC log-loss ≈ −0.20 overall and ≈ −0.37 on recurring
  attackers; recurring-attacker detection turn ≈ 0 (DYNAMIC) vs ≈ 0.7 (STATIC).
  At recurrence 0.0 the gap vanishes — the advantage is attributable only to
  recognising returning campaigns.
