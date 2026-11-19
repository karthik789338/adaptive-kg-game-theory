# EC-POMDG: Import three frozen NetworkX KGs into Neo4j

**Scope:** Neo4j migration **Subphase 2/2**. Works on the XDC (`ecpomdg-ka9d9`) and deploys onto the `kg` VM, using the already-installed Neo4j Community 2026.09.0 server.

## Execution

1. Upload `ecpomdg_neo4j_three_kg_migration.zip` to your XDC home directory in JupyterHub.
2. From the XDC terminal:

   ```bash
   mkdir -p ~/ecpomdg_setup/neo4j_knowledge_graph_migration
   python3 -m zipfile -e ~/ecpomdg_neo4j_three_kg_migration.zip \
     ~/ecpomdg_setup/neo4j_knowledge_graph_migration
   cd ~/ecpomdg_setup/neo4j_knowledge_graph_migration
   bash -n deploy_and_import_three_frozen_knowledge_graphs.sh
   set -o pipefail
   bash deploy_and_import_three_frozen_knowledge_graphs.sh \
     | tee ~/ecpomdg_audit/neo4j_knowledge_graph_migration/neo4j_three_kg_deployment.log
   ```

The script prompts for the **existing** Neo4j admin password via SSH TTY. Password input is hidden and is never written to the deployment or audit files. Do not paste the password into chat.

## Expected final results

- `general_cyber`: 6,171 nodes / 31,654 relationships
- `power_grid_ics`: 467 nodes / 1,800 relationships
- `component_topology`: 104 nodes / 176 relationships
- Total: **6,742 nodes and 33,630 relationships**.
- A `NEO4J_THREE_FROZEN_KGS_MIGRATION: PASS` is shown only after comparing the complete record properties, relationship types, source/target endpoints, multiplicities, and original canonical JSON records.

## Design decisions

- Original node IDs preserved in `kg_original_id` and `id`; original edge record preserved in `kg_record_json`.
- Distinct `kg_uid` (`<namespace>::<original_id>`) and an `kg_namespace` on every node; namespaces are additional labels `GeneralCyber`, `ICSCyber`, `ComponentTopology` in a single Community database.
- Every original relationship type is used as a Neo4j relationship type, with original type name also stored in the `relation` property. Parallel edges use distinct `kg_edge_uid` values.
- `kg_record_json` and `kg_record_sha256` retain the lossless original record. Unsupported nested values are stored as canonical JSON-string properties, rather than discarded.
- Transactions use `MERGE` and are safe to re-run after partial failures. A preflight blocks unrelated nodes and relationships in the database. Existing graph IDs must continue to match their source records; final audits catch any mismatches.
- The import contains **no** cross-KG inferred links; those are a separate, subsequent validated integration phase.
- Sources and HTML visualizations are read-only; the importer does **not** stop Neo4j or replace graph files.

## Audit outputs

On `kg`:
`~/ecpomdg/neo4j_knowledge_graph_migration/results/neo4j_three_kg_migration_validation_summary.json`

On XDC:
`~/ecpomdg_audit/neo4j_knowledge_graph_migration/neo4j_three_kg_migration_validation_summary.json`

The deployment also writes SHA-256 manifests for the importer and validation summary.
