#!/usr/bin/env python3
"""Phase 3D.2A: live online Neo4j commit/read barrier before defender decision.

Only the experiment's SPHERE endpoints are used. Real endpoint traffic is
observe-only and SELECT-only; the only permissible control EXECUTE is on the
isolated decoy, and only after a one-use authorization has been consumed.
This does not change Bayesian likelihoods or establish KG efficacy; no network redirect or full Markov game.

Usage: PYTHONPATH="$HOME/ecpomdg:$HOME/ecpomdg_setup/multistage_game" \
    python3 validate_phase3d2a_live_neo4j_predecision_integration.py --mode NO_KG
Negative path: add --simulate-redirect-failure (no decoy control sent).
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HOME = Path.home()
SETUP = HOME / "ecpomdg_setup" / "multistage_game"
AUDIT = HOME / "ecpomdg_audit" / "multistage_game" / "live_action_gated_decoy"
for package_parent in (HOME / "ecpomdg", SETUP,
                       HOME / "ecpomdg_setup" / "dynamic_knowledge_graph"):
    sys.path.insert(0, str(package_parent))

from ecpomdg_phase3d2a_online_kg_transport import (  # noqa: E402
    create_online_snapshot, commit_and_read_live,
)
from ecpomdg_user_space_action_gate import (  # noqa: E402
    UserSpaceActionGate, FIXED_DECOY_TARGET,
)
from ec_pomdg.multistage_attack_belief_runtime import (  # noqa: E402
    KnowledgeMode, MultiStageBeliefUpdater, StageEvidence,
)
from ec_pomdg.belief_conditioned_multistage_defender_policy import (  # noqa: E402
    BeliefConditionedMultiStageDefenderPolicy,
)
from ec_pomdg.five_stage_ecpomdg_engine import MultiStageDefenderView  # noqa: E402
from ec_pomdg.phase2a_game_contract import DefenderAction  # noqa: E402

REMOTE_LOGS = {
    "real_sensor": ("controller", "~/ecpomdg/multistage_live/logs/iec104_real_multistage_sensor_events.jsonl"),
    "real_controller": ("controller", "~/ecpomdg/iec104_controller_decoy/logs/iec104_real_controller_events.jsonl"),
    "decoy_sensor": ("decoy", "~/ecpomdg/multistage_live/logs/iec104_decoy_multistage_sensor_events.jsonl"),
    "decoy_controller": ("decoy", "~/ecpomdg/iec104_controller_decoy/logs/iec104_decoy_controller_events.jsonl"),
    "operational": ("collector", "~/ecpomdg/telemetry_ground_truth/logs/defender_operational_observation_events.jsonl"),
    "plant": ("gridsim", "~/ecpomdg/t2_gridsim/logs/plant_service_events.jsonl"),
}
ATTACK_PY = '"$HOME/ecpomdg/venvs/iec104_attack/bin/python"'
ATTACK_ROOT = '"$HOME/ecpomdg/industroyer_inspired_iec104/app'
OBSERVE = (f'{ATTACK_PY} {ATTACK_ROOT}/industroyer_inspired_iec104_emulator.py" '
           '--target real --scenario observe')
SELECT_REAL = (f'{ATTACK_PY} {ATTACK_ROOT}/iec104_real_select_only_probe.py"')
DECOY_ONLY = (f'{ATTACK_PY} {ATTACK_ROOT}/industroyer_inspired_iec104_emulator.py" '
              '--target decoy --scenario p_curtail')
API_CODE = (
    "import urllib.request;"
    "u='http://10.50.0.20:9202/operational-observations';"
    "print(urllib.request.urlopen(u,timeout=10).read().decode())"
)
STATE_CODE = (
    "import urllib.request;"
    "u='http://10.40.0.20:8765/state';"
    "print(urllib.request.urlopen(u,timeout=6).read().decode())"
)
EVIDENCE_PREFIX = (
    StageEvidence.NETWORK_RECON,
    StageEvidence.IEC104_SESSION_ESTABLISHED,
    StageEvidence.IEC104_INTERROGATION,
    StageEvidence.DER_POINT_ENUMERATION,
)


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def shell(*args: str, timeout: int = 90) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"Command {args[0:2]} failed: {proc.stderr[-1200:]} {proc.stdout[-600:]}")
    return proc.stdout


def ssh(host: str, command: str, timeout: int = 90) -> str:
    require(host in {"attacker", "controller", "decoy", "collector", "gridsim", "defender"},
            "SSH host not allowlisted")
    return shell("ssh", host, command, timeout=timeout)


def api_records() -> list[dict]:
    payload = json.loads(ssh("defender", "python3 -c " + shlex.quote(API_CODE), timeout=20))
    require(payload.get("ok") is True and isinstance(payload.get("observations"), list),
            "Trusted operational API unavailable")
    records = payload["observations"]
    require(all(isinstance(r, dict) for r in records), "Unexpected API record")
    return records


def new_real_rows(baseline_ids: set[str]) -> list[dict]:
    return sorted(
        (r for r in api_records() if r.get("event_id") not in baseline_ids
         and r.get("asset_id") == "asset-field-001"),
        key=lambda r: r.get("collector_ts_utc", ""),
    )


def await_rows(predicate, baseline_ids: set[str], timeout_s: float = 22) -> list[dict]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = new_real_rows(baseline_ids)
        if predicate(r):
            return r
        time.sleep(0.35)
    raise RuntimeError("Fresh trusted IEC-104 evidence timed out")


def ordered_prefix(rows: list[dict]) -> list[dict] | None:
    types = ("iec104_connection_request", "iec104_session_established", "iec104_interrogation")
    # Prefer the latest possible complete connection→session→GI→reads chain.
    matches = []
    for start in (i for i, r in enumerate(rows) if r.get("event_type") == types[0]):
        chain = [rows[start]]
        cursor = start + 1
        for etype in types[1:]:
            hit = next((i for i in range(cursor, len(rows)) if rows[i].get("event_type") == etype
                        and rows[i].get("asset_id") == "asset-field-001"), None)
            if hit is None:
                break
            chain.append(rows[hit]); cursor = hit + 1
        if len(chain) != 3:
            continue
        reads = {}
        for row in rows[cursor:]:
            if row.get("event_type") == "iec104_point_read" and row.get("ioa") in (11, 12, 13):
                reads.setdefault(row["ioa"], row)
        if set(reads) == {11, 12, 13}:
            matches.append(chain + [reads[11]])
    return matches[-1] if matches else None


def make_view(belief, update, budget, active, previous, step):
    return MultiStageDefenderView(
        belief=dict(belief),
        map_stage=update.map_stage,
        map_probability=update.map_probability,
        entropy_bits=update.entropy_bits,
        status=SimpleNamespace(
            decoy_active=active,
            real_controller_contained=False,
            defense_budget_remaining=budget,
        ),
        previous_defender_action=previous.value,
        step_index=step,
        episode_done=False,
    )


def counters():
    return {name: int(ssh(host, f"wc -l < {path}").strip())
            for name, (host, path) in REMOTE_LOGS.items()}


def collect_deltas(start, destination):
    result = {}
    for name, (host, path) in REMOTE_LOGS.items():
        text = ssh(host, f"tail -n +{start[name] + 1} {path}")
        (destination / f"{name}_delta.jsonl").write_text(text)
        result[name] = [json.loads(line) for line in text.splitlines() if line.strip()]
    return result


def plant_state():
    return json.loads(ssh("controller", "python3 -c " + shlex.quote(STATE_CODE)))


def plant_differences(before, after):
    before, after = before.get("state", before), after.get("state", after)
    fields = {"command_p_kw": 0.05, "command_q_kvar": 0.05,
              "p_injection_kw": 0.05, "q_injection_kvar": 0.05,
              "bus675_mean_voltage_pu": 0.0001}
    return {key: {"before": float(before[key]), "after": float(after[key]),
                  "difference": abs(float(after[key]) - float(before[key])), "tolerance": tol}
            for key, tol in fields.items()}


def listener_ready(ip: str, host: str) -> bool:
    require((ip, host) in {("10.30.0.10", "controller"),
                           ("10.30.0.99", "decoy")}, "Listener check not allowlisted")
    return f"{ip}:2404" in ssh(host, "ss -ltn")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("NO_KG",), required=True)
    parser.add_argument("--simulate-redirect-failure", action="store_true",
                        help="Emulate a failed gate-level redirect; no decoy control is sent")
    args = parser.parse_args()
    if args.simulate_redirect_failure and args.mode == "NO_KG":
        parser.error("--simulate-redirect-failure requires a policy that selects REDIRECT")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = AUDIT / (f"{run_id}_{args.mode.lower()}" +
                   ("_failed_redirect" if args.simulate_redirect_failure else ""))
    out.mkdir(parents=True, exist_ok=False)

    require(listener_ready("10.30.0.10", "controller"), "Real listener unavailable")
    require(listener_ready("10.30.0.99", "decoy"), "Decoy listener unavailable at episode start")
    print("LAB_ENDPOINTS_READY: PASS", flush=True)
    before = plant_state()
    (out / "plant_before.json").write_text(json.dumps(before, indent=2) + "\n")
    start = counters()
    baseline_ids = {r["event_id"] for r in api_records() if isinstance(r.get("event_id"), str)}
    (out / "start_metadata.json").write_text(json.dumps({
        "mode": args.mode, "episode_id": run_id, "start_time_utc": utcnow(),
        "baseline_observation_ids_count": len(baseline_ids),
        "simulate_redirect_failure": args.simulate_redirect_failure,
    }, indent=2) + "\n")

    # Real controller: observe-only; never issue a real EXECUTE.
    observed_stdout = ssh("attacker", OBSERVE, timeout=65)
    (out / "real_observe_stdout.log").write_text(observed_stdout)
    require("GENERAL_INTERROGATION: PASS" in observed_stdout and "command frames: 0" in observed_stdout,
            "Real observe-only operation failed")
    fresh = await_rows(lambda r: ordered_prefix(r) is not None, baseline_ids)
    prefix = ordered_prefix(fresh)
    require(prefix is not None and len({r["event_id"] for r in prefix}) == 4,
            "Cannot establish distinct real protocol prefix events")

    mode = KnowledgeMode(args.mode)
    updater = MultiStageBeliefUpdater(mode=mode)
    policy = BeliefConditionedMultiStageDefenderPolicy()
    belief = updater.initial_belief()
    for evidence in EVIDENCE_PREFIX:
        update = updater.update(belief=belief, evidence=evidence,
                                defender_action=DefenderAction.MONITOR)
        belief = dict(update.posterior)
    before_select_action = policy.decide(
        make_view(belief, update, 4, False, DefenderAction.MONITOR, 4)
    )
    print("POST_ENUMERATION_ACTION:", before_select_action.value, flush=True)

    # The SELECT event_id does not exist yet, so initialize with a sentinel.
    # Only this trusted operational API record is subsequently allowed to bind it.
    gate = UserSpaceActionGate(run_id, args.mode, expected_select_id="AWAITING_FRESH_SELECT")
    require(before_select_action == DefenderAction.ACTIVATE_DECOY,
            "Frozen policy did not activate decoy; fail closed")
    require(gate.apply_action(before_select_action.value, decoy_listener_verified=True),
            "Gate refused decoy activation")
    print("DECOY_ARMED_IN_COORDINATOR_BEFORE_SELECT: PASS", flush=True)

    # Fresh SELECT-only probe sends QOS=0x80; no real execute path exists here.
    select_stdout = ssh("attacker", SELECT_REAL, timeout=35)
    (out / "real_select_only_stdout.log").write_text(select_stdout)
    require("SELECT_SENT: PASS" in select_stdout and "EXECUTE_SENT: False" in select_stdout,
            "Real SELECT-only probe did not finish cleanly")
    fresh = await_rows(lambda r: any(
        row.get("event_type") == "iec104_select" and row.get("asset_id") == "asset-field-001"
        and row.get("ioa") == 100 and row.get("command_phase") == "select"
        and float(row.get("requested", -1)) == 200.0 for row in r), baseline_ids)
    selects = [r for r in fresh if r.get("event_type") == "iec104_select"
               and r.get("asset_id") == "asset-field-001" and r.get("ioa") == 100
               and r.get("command_phase") == "select" and r.get("asdu_type") == 50
               and r.get("cause") == 6 and r.get("common_address") == 47
               and float(r.get("requested", -1)) == 200.0]
    require(len(selects) == 1, "Ambiguous fresh real SELECT evidence")
    select = selects[0]
    require(select["event_id"] not in {r["event_id"] for r in prefix}, "SELECT event ID duplicated")
    # Bind only once, from the fresh trusted operational API response.
    require(gate.expected_select_id == "AWAITING_FRESH_SELECT" and not gate.saw_real_select
            and gate.decoy_armed, "Invalid SELECT-binding lifecycle")
    gate.expected_select_id = select["event_id"]
    require(gate.observe_real_select(select), "User-space gate rejected real SELECT")
    require(not any(r.get("event_type") == "iec104_execute" and
                    r.get("asset_id") == "asset-field-001" for r in fresh),
            "Real controller executed prior to decision")

    # Mandatory synchronous, fail-closed online Neo4j commit + feature readout.
    # This is a graph-observation dependency, NOT a new Bayesian likelihood.
    snapshot = create_online_snapshot(
        run_id, fresh,
        [r["event_id"] for r in prefix] + [select["event_id"]],
        select["event_id"], utcnow(),
    )
    online_graph = commit_and_read_live(out, snapshot)
    print("GRAPH_COMMIT_AND_READ_BEFORE_POLICY_DECISION: PASS", flush=True)

    update = updater.update(belief=belief, evidence=StageEvidence.CONTROL_SELECT,
                            defender_action=DefenderAction.ACTIVATE_DECOY)
    belief = dict(update.posterior)
    after_select_action = policy.decide(make_view(
        belief, update, gate.remaining_budget, True, DefenderAction.ACTIVATE_DECOY, 5
    ))
    # Integration-only first run: never authorize decoy or real execution.
    require(after_select_action == DefenderAction.MONITOR,
            "First-run NO_KG baseline unexpectedly requested a control action; fail closed")
    print("ACTIVE_POLICY:", args.mode, flush=True)
    print("P_CONTROL:", round(belief["CONTROL_MANIPULATION"], 6), flush=True)
    print("POST_SELECT_ACTION:", after_select_action.value, flush=True)

    decision_at_utc = utcnow()
    dispatch_performed = False
    redirect_failed = False
    if after_select_action == DefenderAction.REDIRECT:
        currently_verified = (not args.simulate_redirect_failure
                              and listener_ready(FIXED_DECOY_TARGET, "decoy"))
        accepted = gate.apply_action("REDIRECT", decoy_listener_verified=currently_verified)
        if accepted:
            token = gate.current_permit
            require(token is not None, "Accepted redirect failed to create permit")
            require(gate.consume_decoy_permit(token, target=FIXED_DECOY_TARGET),
                    "One-use decoy authorization rejected")
            require(gate.current_permit is None, "Consumed permit remained reusable")
            # Dispatch is downstream of consuming the single-use permit.
            stdout = ssh("attacker", DECOY_ONLY, timeout=95)
            (out / "decoy_control_transaction_stdout.log").write_text(stdout)
            require("INDUSTROYER_INSPIRED_IEC104_EMULATION: PASS" in stdout,
                    "Decoy transaction failed")
            dispatch_performed = True
            print("GATE_AUTHORIZED_DECOY_ONLY_DISPATCH: PASS", flush=True)
        else:
            redirect_failed = True
            require(gate.current_permit is None, "Failed redirect leaked a permit")
            require(gate.apply_action("CONTAIN"), "Budgeted coordinator CONTAIN failed")
            print("REDIRECT_FAILURE_CONTAINED_IN_COORDINATOR: PASS", flush=True)
    elif after_select_action == DefenderAction.MONITOR:
        require(gate.apply_action("MONITOR"), "MONITOR unexpectedly denied")
        require(gate.current_permit is None, "MONITOR must not authorize dispatch")
        print("MONITOR_WITHHELD_CONTROL: PASS", flush=True)
    elif after_select_action == DefenderAction.CONTAIN:
        require(gate.apply_action("CONTAIN"), "Coordinator CONTAIN denied")
        print("CONTAIN_DISPATCH_DISABLED: PASS", flush=True)
    else:
        raise RuntimeError(f"Unsupported next action {after_select_action.value}; fail closed")

    time.sleep(3)
    delta = collect_deltas(start, out)
    after = plant_state()
    (out / "plant_after.json").write_text(json.dumps(after, indent=2) + "\n")
    changes = plant_differences(before, after)
    require(all(d["difference"] <= d["tolerance"] for d in changes.values()),
            "Real plant state changed outside tolerances")
    real_exec = [r for r in delta["real_controller"] if r.get("event") == "iec104_execute"]
    real_raw_exec = [r for r in delta["real_sensor"] if r.get("event") in {
        "iec104_execute_raw", "iec104_execute"}]
    real_ops_exec = [r for r in delta["operational"]
                     if r.get("asset_id") == "asset-field-001"
                     and r.get("event_type") == "iec104_execute"]
    require(not real_exec and not real_raw_exec and not real_ops_exec,
            "Real controller executed unexpectedly")
    require(any(r.get("event_id") == select["event_id"] and r.get("asset_id") == "asset-field-001"
                for r in delta["operational"]), "Selected event missing from operational log delta")
    decoy_exec = [r for r in delta["decoy_controller"] if r.get("event") == "iec104_execute"
                  and r.get("ioa") == 100 and r.get("mode") == "decoy"]
    decoy_vals = [float(r.get("requested", -1)) for r in decoy_exec]
    if dispatch_performed:
        require(decoy_vals == [200.0, 400.0], f"Decoy execute/restore mismatch: {decoy_vals}")
        require(any(r.get("asset_id") == "asset-field-002"
                    and r.get("event_type") == "iec104_execute"
                    and float(r.get("requested", -1)) == 200.0
                    for r in delta["operational"]), "Trusted decoy execution missing")
        outcome = "GAME_MEDIATED_DECOY_TRANSACTION_VERIFIED"
    else:
        require(not decoy_exec, "Decoy executed despite no gate permit")
        outcome = ("SIMULATED_REDIRECT_FAILURE_CONTAINED_IN_COORDINATOR"
                   if redirect_failed else "CONTROL_WITHHELD_CENSORED")

    summary = {
        "episode_id": run_id,
        "mode": args.mode,
        "fresh_iec104_observations": True,
        "source_event_ids": [r["event_id"] for r in prefix] + [select["event_id"]],
        "real_select_event_id": select["event_id"],
        "post_der_action": before_select_action.value,
        "post_select_action": after_select_action.value,
        "p_control_manipulation": belief["CONTROL_MANIPULATION"],
        "defender_decision_time_utc": decision_at_utc,
        "outcome": outcome,
        "online_graph_readback": online_graph,
        "graph_features_used_for_bayesian_likelihood": False,
        "decoy_execute_values": decoy_vals,
        "real_execute_count": len(real_exec) + len(real_raw_exec) + len(real_ops_exec),
        "plant_state_differences": changes,
        "simulated_redirect_failure": args.simulate_redirect_failure,
        "gate_summary": gate.summary(),
        "limits": {
            "real_controller_execute_attempted": False,
            "transparent_network_redirection": False,
            "kernel_network_containment": False,
            "decoy_pre_running": True,
            "observer_and_select_are_separate_iec104_sessions": True,
            "full_stochastic_live_game": False,
            "online_neo4j_graph_update_used": True,
            "online_neo4j_feature_query_before_decision": True,
            "graph_features_used_for_bayesian_likelihood": False,
            "full_dynamic_kg_causal_advantage": False,
        },
    }
    (out / "live_action_gated_episode_result.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    (out / "fresh_real_operational_evidence.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in fresh)
    )
    print("REAL_NO_EXECUTE: PASS")
    print("REAL_PLANT_STATE_UNCHANGED: PASS")
    print("ONE_USE_DISPATCH_PERMITS_CONSUMED:", len(gate.used_permits))
    print("MODEL_BUDGET_REMAINING:", gate.remaining_budget)
    print("OBSERVED_STATUS:", outcome)
    print("ONLINE_GRAPH_COMMIT_AND_READ_BARRIER: PASS")
    print("DYNAMIC_KG_BELIEF_ADVANTAGE_ESTABLISHED: NO")
    print("PHASE3D2A_LIVE_NEO4J_PREDECISION_INTEGRATION: PASS")
    print("OUTPUT:", out)


if __name__ == "__main__":
    main()
