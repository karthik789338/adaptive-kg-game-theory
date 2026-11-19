#!/usr/bin/env python3
"""LIVE H1 episode on SPHERE -- generalized from your validated driver.

Derived faithfully from ecpomdg_setup/multistage_game/
validate_live_action_gated_decoy_episode.py (same ssh flow, same
MultiStageBeliefUpdater, same UserSpaceActionGate, same evidence matching).
Surgical changes only:
  * --policy {MONITOR_ONLY,FIXED_SCHEDULE,STAGE_AGNOSTIC,BELIEF_ADAPTIVE}
  * the belief-specific "must activate decoy / fail closed" asserts are relaxed
    so any policy's action path is allowed
  * --benign runs an attack-free (observe-only, no SELECT) episode to measure
    wasted defensive cost when no attack is present
  * the result JSON records policy, condition, actions, gate cost, outcome

SAFETY: unchanged from your driver -- the real controller is NEVER executed;
only the decoy may execute, via a one-use gate permit. "Physical impact on the
real grid" is therefore not measurable here by design; H1 live measures decoy
diversion, defender cost, outcome category and latency.

Run on the orchestration host that has ssh to all nodes, with your package path:
  PYTHONPATH="$HOME/ecpomdg:$HOME/ecpomdg_setup/multistage_game" \
    python3 h1_live_episode.py --policy BELIEF_ADAPTIVE --mode DYNAMIC_KG
  add --benign for an attack-free episode.
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
AUDIT = HOME / "ecpomdg_audit" / "multistage_game" / "h1_live"
for package_parent in (HOME / "ecpomdg", SETUP, Path(__file__).resolve().parent):
    sys.path.insert(0, str(package_parent))

from ecpomdg_user_space_action_gate import UserSpaceActionGate, FIXED_DECOY_TARGET  # noqa: E402
from ec_pomdg.multistage_attack_belief_runtime import (  # noqa: E402
    KnowledgeMode, MultiStageBeliefUpdater, StageEvidence,
)
from ec_pomdg.belief_conditioned_multistage_defender_policy import (  # noqa: E402
    BeliefConditionedMultiStageDefenderPolicy,
)
from ec_pomdg.five_stage_ecpomdg_engine import MultiStageDefenderView  # noqa: E402
from ec_pomdg.phase2a_game_contract import DefenderAction  # noqa: E402
from baseline_policies import get_baseline  # noqa: E402

# --- verbatim from your validated driver ----------------------------------
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
API_CODE = ("import urllib.request;u='http://10.50.0.20:9202/operational-observations';"
            "print(urllib.request.urlopen(u,timeout=10).read().decode())")
STATE_CODE = ("import urllib.request;u='http://10.40.0.20:8765/state';"
              "print(urllib.request.urlopen(u,timeout=6).read().decode())")
EVIDENCE_PREFIX = (StageEvidence.NETWORK_RECON, StageEvidence.IEC104_SESSION_ESTABLISHED,
                   StageEvidence.IEC104_INTERROGATION, StageEvidence.DER_POINT_ENUMERATION)
ACTION_COST = {"MONITOR": 0, "ACTIVATE_DECOY": 1, "REDIRECT": 1, "CONTAIN": 2}


def require(c, reason):
    if not c:
        raise RuntimeError(reason)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def shell(*args, timeout=90):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"Command {args[0:2]} failed: {p.stderr[-1200:]} {p.stdout[-600:]}")
    return p.stdout


def ssh(host, command, timeout=90):
    require(host in {"attacker", "controller", "decoy", "collector", "gridsim", "defender"}, "SSH host not allowlisted")
    return shell("ssh", host, command, timeout=timeout)


def api_records():
    payload = json.loads(ssh("defender", "python3 -c " + shlex.quote(API_CODE), timeout=20))
    require(payload.get("ok") is True and isinstance(payload.get("observations"), list), "Trusted operational API unavailable")
    return payload["observations"]


def new_real_rows(baseline_ids):
    return sorted((r for r in api_records() if r.get("event_id") not in baseline_ids
                   and r.get("asset_id") == "asset-field-001"),
                  key=lambda r: r.get("collector_ts_utc", ""))


def await_rows(predicate, baseline_ids, timeout_s=22):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = new_real_rows(baseline_ids)
        if predicate(r):
            return r
        time.sleep(0.35)
    raise RuntimeError("Fresh trusted IEC-104 evidence timed out")


def ordered_prefix(rows):
    types = ("iec104_connection_request", "iec104_session_established", "iec104_interrogation")
    matches = []
    for start in (i for i, r in enumerate(rows) if r.get("event_type") == types[0]):
        chain = [rows[start]]; cursor = start + 1
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


def make_view(belief, update, budget, active, previous, step, contained=False):
    return MultiStageDefenderView(
        belief=dict(belief), map_stage=update.map_stage, map_probability=update.map_probability,
        entropy_bits=update.entropy_bits,
        status=SimpleNamespace(decoy_active=active, real_controller_contained=contained,
                               defense_budget_remaining=budget),
        previous_defender_action=previous, step_index=step, episode_done=False)


def counters():
    return {name: int(ssh(host, f"wc -l < {path}").strip()) for name, (host, path) in REMOTE_LOGS.items()}


def collect_deltas(start, destination):
    result = {}
    for name, (host, path) in REMOTE_LOGS.items():
        text = ssh(host, f"tail -n +{start[name] + 1} {path}")
        (destination / f"{name}_delta.jsonl").write_text(text)
        result[name] = [json.loads(line) for line in text.splitlines() if line.strip()]
    return result


def plant_state():
    return json.loads(ssh("controller", "python3 -c " + shlex.quote(STATE_CODE)))


def listener_ready(ip, host):
    require((ip, host) in {("10.30.0.10", "controller"), ("10.30.0.99", "decoy")}, "Listener check not allowlisted")
    return f"{ip}:2404" in ssh(host, "ss -ltn")


# --- policy abstraction -----------------------------------------------------
def make_policy(name):
    if name == "BELIEF_ADAPTIVE":
        return BeliefConditionedMultiStageDefenderPolicy()
    return get_baseline(name)


def decide(policy, view) -> str:
    r = policy.decide(view)
    return r.value if hasattr(r, "value") else str(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", choices=("MONITOR_ONLY", "FIXED_SCHEDULE", "STAGE_AGNOSTIC", "BELIEF_ADAPTIVE"), required=True)
    ap.add_argument("--mode", choices=("NO_KG", "STATIC_KG", "DYNAMIC_KG"), default="DYNAMIC_KG")
    ap.add_argument("--benign", action="store_true", help="attack-free episode (observe-only, no SELECT)")
    args = ap.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    tag = f"{run_id}_{args.policy.lower()}_{args.mode.lower()}" + ("_benign" if args.benign else "_attack")
    out = AUDIT / tag
    out.mkdir(parents=True, exist_ok=True)

    require(listener_ready("10.30.0.10", "controller"), "Real listener unavailable")
    require(listener_ready("10.30.0.99", "decoy"), "Decoy listener unavailable at episode start")
    before = plant_state()
    (out / "plant_before.json").write_text(json.dumps(before, indent=2) + "\n")
    start = counters()
    baseline_ids = {r["event_id"] for r in api_records() if isinstance(r.get("event_id"), str)}

    # Enumeration evidence (same for attack and benign -- legitimate polling looks like this).
    observed = ssh("attacker", OBSERVE, timeout=65)
    (out / "real_observe_stdout.log").write_text(observed)
    require("GENERAL_INTERROGATION: PASS" in observed and "command frames: 0" in observed, "Observe-only failed")
    fresh = await_rows(lambda r: ordered_prefix(r) is not None, baseline_ids)
    prefix = ordered_prefix(fresh)
    require(prefix is not None, "Cannot establish real protocol prefix")

    mode = KnowledgeMode(args.mode)
    updater = MultiStageBeliefUpdater(mode=mode)
    policy = make_policy(args.policy)
    belief = updater.initial_belief()
    for evidence in EVIDENCE_PREFIX:
        update = updater.update(belief=belief, evidence=evidence, defender_action=DefenderAction.MONITOR)
        belief = dict(update.posterior)

    budget = 4
    cost = 0
    actions = []
    gate = UserSpaceActionGate(run_id, args.mode, expected_select_id="AWAITING_FRESH_SELECT")

    # Decision 1: post-enumeration (step 4). Any policy allowed (asserts relaxed).
    a1 = decide(policy, make_view(belief, update, budget, False, "MONITOR", 4))
    actions.append(a1)
    decoy_armed = False
    if a1 == "ACTIVATE_DECOY":
        if gate.apply_action("ACTIVATE_DECOY", decoy_listener_verified=True):
            decoy_armed = True; budget -= 1; cost += ACTION_COST["ACTIVATE_DECOY"]
    elif a1 == "CONTAIN":
        if gate.apply_action("CONTAIN"):
            budget -= 2; cost += ACTION_COST["CONTAIN"]
    # (MONITOR / REDIRECT-without-decoy -> no-op at this step)

    diverted = False
    outcome = None

    if args.benign:
        # Attack-free: no SELECT is ever sent; legitimate operations only.
        outcome = "BENIGN_NO_CONTROL" + ("_DECOY_WASTED" if decoy_armed else "")
    else:
        # SELECT-only probe (same as your driver); never a real execute.
        select_stdout = ssh("attacker", SELECT_REAL, timeout=35)
        (out / "real_select_only_stdout.log").write_text(select_stdout)
        require("SELECT_SENT: PASS" in select_stdout and "EXECUTE_SENT: False" in select_stdout, "SELECT probe failed")
        fresh = await_rows(lambda r: any(
            row.get("event_type") == "iec104_select" and row.get("asset_id") == "asset-field-001"
            and row.get("ioa") == 100 and row.get("command_phase") == "select"
            and float(row.get("requested", -1)) == 200.0 for row in r), baseline_ids)
        selects = [r for r in fresh if r.get("event_type") == "iec104_select" and r.get("asset_id") == "asset-field-001"
                   and r.get("ioa") == 100 and r.get("command_phase") == "select" and float(r.get("requested", -1)) == 200.0]
        require(len(selects) >= 1, "No fresh real SELECT evidence")
        select = selects[-1]
        if decoy_armed:
            gate.expected_select_id = select["event_id"]
            gate.observe_real_select(select)

        update = updater.update(belief=belief, evidence=StageEvidence.CONTROL_SELECT,
                                defender_action=DefenderAction.ACTIVATE_DECOY if decoy_armed else DefenderAction.MONITOR)
        belief = dict(update.posterior)
        a2 = decide(policy, make_view(belief, update, budget, decoy_armed, a1, 5))
        actions.append(a2)
        (out / "belief_post_select.json").write_text(json.dumps(
            {"p_control": belief.get("CONTROL_MANIPULATION"), "map_stage": update.map_stage,
             "action": a2}, indent=2) + "\n")

        if a2 == "REDIRECT" and decoy_armed and gate.apply_action(
                "REDIRECT", decoy_listener_verified=listener_ready(FIXED_DECOY_TARGET, "decoy")):
            budget -= 1; cost += ACTION_COST["REDIRECT"]
            token = gate.current_permit
            if token is not None and gate.consume_decoy_permit(token, target=FIXED_DECOY_TARGET):
                stdout = ssh("attacker", DECOY_ONLY, timeout=95)
                (out / "decoy_control_transaction_stdout.log").write_text(stdout)
                diverted = "INDUSTROYER_INSPIRED_IEC104_EMULATION: PASS" in stdout
            outcome = "DECOY_DIVERSION" if diverted else "REDIRECT_NO_DISPATCH"
        elif a2 == "CONTAIN" and budget >= 2 and gate.apply_action("CONTAIN"):
            budget -= 2; cost += ACTION_COST["CONTAIN"]; outcome = "CONTAINED"
        else:
            gate.apply_action("MONITOR")
            outcome = "CONTROL_WITHHELD"

    time.sleep(2)
    delta = collect_deltas(start, out)
    after = plant_state()
    (out / "plant_after.json").write_text(json.dumps(after, indent=2) + "\n")
    # SAFETY INVARIANT (unchanged): the real controller must never execute.
    real_exec = [r for r in delta["real_controller"] if r.get("event") == "iec104_execute"]
    require(not real_exec, "SAFETY VIOLATION: real controller executed")

    summary = {
        "episode_id": run_id, "policy": args.policy, "mode": args.mode, "condition": "benign" if args.benign else "attack",
        "actions": actions, "defender_cost": cost, "decoy_diverted": bool(diverted),
        "outcome": outcome, "real_execute_count": len(real_exec),
        "gate_summary": gate.summary() if hasattr(gate, "summary") else None,
        "decision_time_utc": utcnow(),
    }
    (out / "h1_live_episode_result.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("H1_LIVE_EPISODE:", json.dumps({k: summary[k] for k in
          ("policy", "mode", "condition", "actions", "defender_cost", "decoy_diverted", "outcome")}))
    print("REAL_NO_EXECUTE: PASS")
    print("OUTPUT:", out)


if __name__ == "__main__":
    main()
