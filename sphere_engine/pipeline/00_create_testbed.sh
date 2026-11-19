#!/usr/bin/env bash
# =============================================================================
# Stage 00 - create the SPHERE testbed from topology/sphere-testbed.py.
#
# Run on the SPHERE XDC/orchestration host. The exact Merge commands depend on
# your SPHERE project; the canonical mergexp workflow is shown. Adjust PROJECT.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="${SPHERE_PROJECT:-ecpomdg}"
EXPERIMENT="${SPHERE_EXPERIMENT:-ecpomdg-powergrid}"

echo "== 00.1 push + realize the experiment topology =="
# mergexp / Merge CLI (install: pip install mergexp ; configure 'mrg login'):
mrg push  "$PROJECT" topology/sphere-testbed.py        || echo "  (adjust to your 'mrg push' invocation)"
mrg realize "$PROJECT.$EXPERIMENT"                     || true
mrg xdc attach "$PROJECT.$EXPERIMENT"                  || true
echo "  nodes expected: attacker edgegw scada historian fieldgw controller decoy gridsim collector kg defender operator"

echo "== 00.2 install per-node dependencies via Ansible groups =="
# The topology tags each node with properties['group']; use those inventory groups.
# Attacker/controller/decoy need the IEC-104 stack (c104); kg needs neo4j; all need python3.
cat > /tmp/ecpomdg_install.yml <<'YML'
- hosts: all
  tasks:
    - apt: name=python3,python3-pip,python3-venv state=present
      become: true
- hosts: attack:field_control:deception
  tasks:
    - pip: name=c104 executable=pip3
- hosts: knowledge
  tasks:
    - pip: name=neo4j executable=pip3
- hosts: defense:telemetry
  tasks:
    - pip: name=numpy,pandas,networkx,neo4j executable=pip3
YML
ansible-playbook -i "$PROJECT.$EXPERIMENT," /tmp/ecpomdg_install.yml || \
  echo "  (adjust inventory to your SPHERE Ansible setup; groups come from the topology file)"

echo "== 00.3 start the IEC-104 / plant services on their nodes =="
echo "  controller: iec104_controller_decoy_service.py  (real listener 10.30.0.10:2404)"
echo "  decoy:      iec104_controller_decoy_service.py  (decoy listener 10.30.0.99:2404)"
echo "  gridsim:    OpenDSS plant service on 10.40.0.20:8765"
echo "  collector:  telemetry_collector_service.py      (operational API 10.50.0.20:9202)"
echo "  (these are your existing services under ~/ecpomdg/...; start via your Ansible role)"
echo "STAGE 00 DONE - verify: ssh controller 'ss -ltn | grep 2404' and curl gridsim :8765/state"
