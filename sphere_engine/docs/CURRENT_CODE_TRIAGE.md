# Current backup triage

The old backup contains a large amount of phase-specific validation, frozen archives, duplicated checkpoints, and one-off audit code. Do not copy that tree wholesale into the final project.

## Retain as infrastructure

- IEC-104 real/decoy endpoint service.
- Industroyer-inspired IEC-104 attacker emulator.
- Trusted telemetry collector and forwarder.
- Trusted asset registry.
- IEEE-13/OpenDSS topology capture/validation logic.
- Three frozen KG builders and the validated Neo4j importer.
- The five-stage vocabulary and oracle-leakage checks as design references.

## Replace for final science

- Hand-tuned KG affinity multipliers in the old belief model.
- Phase-number-specific dynamic-KG sidecars and synthetic overlay experiments.
- The old `scheduled_containment` baseline in which early containment deterministically forced withdrawal.
- Any H2 comparison where Neo4j features were information-identical to a flattened baseline.
- Any synthetic six-state HMM that does not exactly match the final five-stage game.

## Archive, do not delete immediately

Move the old `ecpomdg_setup/` and `ecpomdg_audit/` trees to a read-only legacy archive after the final folder passes preflight. They are valuable provenance but should not be imported by the final experiment runtime.
