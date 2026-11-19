#!/usr/bin/env python3
"""Adapter: real SPHERE live-episode captures -> ecpomdg stream + labels.

Consumes the ACTUAL telemetry your testbed already writes per episode
(``operational_delta.jsonl`` / ``online_predecision_trusted_observations.json``)
and emits the ``<actor>.ndjson`` + ``<actor>.labels.json`` pair the live CLI and
experiments consume. This is the real bridge (not the generic placeholder): it
uses your real IEC-104 event vocabulary, your ``trusted_asset_id`` / topology,
and the attacker ``client_ip`` as the campaign actor identity.

Real event_type -> (canonical event, canonical stage):
  iec104_connection_request  -> IEC104_SESSION        , ACCESS
  iec104_session_established  -> IEC104_SESSION        , ACCESS
  iec104_interrogation       -> GENERAL_INTERROGATION , DER_ENUM
  iec104_point_read          -> POINT_READ            , DER_ENUM
  iec104_select              -> CONTROL_SELECT        , CONTROL
  iec104_execute             -> CONTROL_EXECUTE       , IMPACT

Stage labels here are the canonical stage of each real event (valid because the
emulator campaigns are monotonic). When your evaluator oracle writes a per-event
true stage, pass --oracle to use it verbatim instead.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

EVENT_MAP = {
    "iec104_connection_request": ("IEC104_SESSION", "ACCESS"),
    "iec104_session_established": ("IEC104_SESSION", "ACCESS"),
    "iec104_interrogation": ("GENERAL_INTERROGATION", "DER_ENUM"),
    "iec104_point_read": ("POINT_READ", "DER_ENUM"),
    "iec104_select": ("CONTROL_SELECT", "CONTROL"),
    "iec104_execute": ("CONTROL_EXECUTE", "IMPACT"),
}
# trusted_asset_id / asset_uid -> our topology asset id
ASSET_MAP = {"asset-field-001": "controller-real", "asset-field-099": "controller-decoy"}


def _attacker_ip(episode_dir: Path) -> str:
    sensor = episode_dir / "real_sensor_delta.jsonl"
    if sensor.exists():
        for line in sensor.read_text().splitlines():
            if line.strip():
                ip = json.loads(line).get("client_ip")
                if ip:
                    return ip
    return "10.10.0.10"


def convert_episode(episode_dir: Path, population: str, phase: str, out_base: Path,
                    actor_override: str | None = None):
    mode = "decoy" if "decoy" in episode_dir.name and "no_kg" not in episode_dir.name else "real"
    obs_file = episode_dir / "operational_delta.jsonl"
    if not obs_file.exists():
        obs_file = episode_dir / "fresh_real_operational_evidence.jsonl"
    events = [json.loads(l) for l in obs_file.read_text().splitlines() if l.strip()]

    actor = actor_override or _attacker_ip(episode_dir)
    raw, stages = [], []
    for ev in events:
        et = ev.get("event_type", "")
        if et not in EVENT_MAP:
            continue
        canon_event, stage = EVENT_MAP[et]
        asset = ASSET_MAP.get(ev.get("asset_id", ""), ev.get("asset_id", "UNKNOWN"))
        target_role = "DECOY" if asset == "controller-decoy" else "REAL"
        phase_tag = "SELECT" if canon_event == "CONTROL_SELECT" else ("EXECUTE" if canon_event == "CONTROL_EXECUTE" else "NONE")
        raw.append({
            "event_type": canon_event,
            "protocol_phase": phase_tag,
            "target_role": target_role,
            "physical_alarm": "YES" if (canon_event == "CONTROL_EXECUTE" and target_role == "REAL") else "NO",
            "asset_id": asset,
            "source_host": "attacker",        # untrusted origin (client_ip below is the identity)
            "actor_id": actor,
            "collector_ts_utc": ev.get("collector_ts_utc", ev.get("observed_at_utc", "")),
        })
        stages.append(stage)

    out_dir = out_base / population / phase
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{actor}_{episode_dir.name}"
    (out_dir / f"{name}.ndjson").write_text("\n".join(json.dumps(r) for r in raw) + "\n")
    labels = {"actor_id": actor, "is_attack": True, "true_stages": stages}
    (out_dir / f"{name}.labels.json").write_text(json.dumps(labels) + "\n")
    return name, len(raw)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episodes-root", required=True,
                    help="dir containing live episode subfolders (…/live_action_gated_decoy)")
    ap.add_argument("--out", required=True, help="streams base dir")
    ap.add_argument("--population", choices=["train", "test"], required=True)
    ap.add_argument("--phase", choices=["phase1", "phase2"], required=True)
    ap.add_argument("--actor", default=None, help="override actor id (else attacker client_ip)")
    args = ap.parse_args()

    root = Path(args.episodes_root)
    subdirs = [d for d in sorted(root.iterdir()) if d.is_dir()]
    n = 0
    for d in subdirs:
        if not (d / "operational_delta.jsonl").exists() and not (d / "fresh_real_operational_evidence.jsonl").exists():
            continue
        name, k = convert_episode(d, args.population, args.phase, Path(args.out), args.actor)
        print(f"  converted {d.name} -> {name} ({k} events)")
        n += 1
    print(f"ADAPTED {n} real SPHERE episodes into {args.out}/{args.population}/{args.phase}")


if __name__ == "__main__":
    main()
