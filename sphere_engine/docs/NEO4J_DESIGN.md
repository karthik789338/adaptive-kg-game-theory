# Neo4j design for H2

Use Neo4j as the final source-of-truth graph backend. NetworkX is optional for local unit tests and figures, but final H2 features should be queried from Neo4j so static and dynamic modes differ only by permitted graph state.

Keep the three knowledge domains logically distinguishable with labels/properties (`general_cyber`, `power_grid_ics`, `component_topology`) while allowing explicit semantic bridge relationships.

Add runtime nodes only for DYNAMIC_KG:

- `(:Episode)`
- `(:RuntimeObservation)`
- `(:RuntimeObservation)-[:NEXT_OBSERVATION]->(:RuntimeObservation)`
- links from observations to trusted assets, IEC-104 semantics, attack techniques/stages, and physical components when those links are derivable from defender-visible data.

Static KG features should capture semantic and topological context at one decision point. Dynamic KG adds temporal-path context from observations already seen in the same episode.

Never write oracle labels into the graph database used by the defender. Evaluator labels belong in a separate results file/database.
