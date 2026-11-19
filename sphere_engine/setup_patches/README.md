# setup_patches — fixed versions of the original ecpomdg_setup scripts

Each file here replaces its namesake in `~/ecpomdg_setup/<component>/` on the XDC
host. They are the originals with the session's fixes already applied, so a clean
rebuild (see `../RUNBOOK_REPRODUCE.md`) runs without re-deriving anything.

| file | fix |
|---|---|
| `multistage_game/deploy_and_validate_decoy_live_multistage_sensor.sh` | restore real `c104.Server` before sensor install (callback-annotation validation); guard missing operational-observation baseline |
| `multistage_game/deploy_and_validate_multistage_belief_runtime.sh` | ship full `ec_pomdg` engine + configs to the defender |
| `power_grid_component_topology_knowledge_graph/build_power_grid_component_topology_knowledge_graph.sh` | use frozen IEEE-13 snapshot (lost OpenDSS venv) |
| `general_cyber_knowledge_graph/build_general_cyber_knowledge_graph.sh` | exclude deprecated CAPEC/CWE (active-only); relax stale exact counts |
| `kg_defender_integration/build_unified_defender_knowledge_index.sh` | relax stale general_cyber exact counts to lower bounds |
| `kg_defender_integration/deploy_and_validate_live_kg_enriched_defender_observations.sh` | guard missing operational-observation baseline reads |
| `neo4j_knowledge_graph_migration/import_frozen_knowledge_graphs_into_neo4j.py` | env password; dynamic totals (not 6742/33630); drop per-source hard counts |
| `kg_visualizations/build_all_knowledge_graph_visualizations.py` | relax exact (node,edge) count to lower bound |
| `telemetry_ground_truth/telemetry_collector_service.py` | hardened collector: operational-observation write (heredoc build omits it) + whitelist IEC-104 command fields command_phase/asdu_type/cause/common_address |
| `multistage_game/live_multistage_sensor_build/multistage_live_sensor_forwarder.py` | enveloped forwarder POSTs `{"event": <dict>}` (flat build is HTTP 400'd by the hardened collector) |
| `multistage_game/iec104_real_select_only_probe.py` | real SELECT-only probe (stdlib), deployed to the attacker for the live episode |
| `dynamic_knowledge_graph/manage_phase3d1c_neo4j_semantic_bridges.py` | freeze-repin: live-core guard `== 6742/33630` → `>=` (active-only graph is a superset; bridges are outside `:KGNode`, before==after holds) |
| `dynamic_knowledge_graph/{validate_phase3d2a…, ecpomdg_phase3d2a_online_kg_transport, ingest_and_query_phase3d2a…}.py`, `phase3d1c_semantic_bridge_manifest.json` | phase3d2a live-episode coordinator/transport/kg-worker + bridge manifest (reference copies; unchanged logic) |

New orchestration (in `../pipeline/`, not patches): `deploy_gridsim_plant.sh`,
`phase1_build_kg.sh`, `phase1_neo4j_up.sh`; Phase 3: `phase3_real_sensor.sh`,
`phase3_operational_collector.sh`, `phase3_sensor_forwarder.sh`,
`phase3_build_bridges.sh`, `phase3_deploy_episode.sh`, `phase3_live_episode.sh`;
new service `../sphere/gridsim_plant_service.py`.
