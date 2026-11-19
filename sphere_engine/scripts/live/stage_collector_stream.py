#!/usr/bin/env python3
"""Stage collector output into the per-actor stream layout the live CLI expects.

On SPHERE the collector writes two NDJSON logs on the telemetry plane:
  * defender_observation_events.jsonl  — defender-visible events
  * experiment_oracle_events.jsonl     — evaluator ground truth (true stage)
This helper groups both by an actor key and emits, under
<out>/<population>/<phase>/:
    <actor>.ndjson        (defender-visible events, one JSON object per line)
    <actor>.labels.json   (evaluator-only: is_attack + true_stages)

This is the ONLY glue specific to your collector transport. If your collector
fields differ, adjust the KEY_MAP below; everything downstream is unchanged.

Defender event line is expected to carry (rename via KEY_MAP as needed):
  event_type, protocol_phase|command_phase, target_role|asset_role,
  physical_alarm, asset_id, source_host, actor_id, collector_ts_utc
Oracle line is expected to carry: actor_id (or source_host), ts, true_stage.
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path

# Map your collector's field names onto the canonical names on the right.
KEY_MAP = {
    "command_phase": "protocol_phase",
    "asset_role": "target_role",
}
CANONICAL = ["event_type", "protocol_phase", "target_role", "physical_alarm",
             "asset_id", "source_host", "actor_id", "collector_ts_utc"]


def _norm(ev: dict) -> dict:
    out = dict(ev)
    for src, dst in KEY_MAP.items():
        if src in out and dst not in out:
            out[dst] = out.pop(src)
    if "actor_id" not in out:
        out["actor_id"] = out.get("source_host", "UNKNOWN")
    if isinstance(out.get("physical_alarm"), bool):
        out["physical_alarm"] = "YES" if out["physical_alarm"] else "NO"
    return {k: out.get(k, "UNKNOWN") for k in CANONICAL}


def _actor(ev: dict, key: str) -> str:
    return str(ev.get(key, ev.get("actor_id", ev.get("source_host", "UNKNOWN"))))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--observations", required=True, help="defender_observation_events.jsonl")
    ap.add_argument("--oracle", required=True, help="experiment_oracle_events.jsonl (evaluator ground truth)")
    ap.add_argument("--out", required=True, help="streams base dir, e.g. data/streams")
    ap.add_argument("--population", choices=["train", "test"], required=True)
    ap.add_argument("--phase", choices=["phase1", "phase2"], required=True)
    ap.add_argument("--actor-key", default="actor_id", help="field used to group an actor/campaign")
    args = ap.parse_args()

    obs_by_actor = defaultdict(list)
    for line in Path(args.observations).read_text().splitlines():
        if line.strip():
            ev = json.loads(line)
            obs_by_actor[_actor(ev, args.actor_key)].append(_norm(ev))

    stages_by_actor = defaultdict(list)
    for line in Path(args.oracle).read_text().splitlines():
        if line.strip():
            o = json.loads(line)
            stages_by_actor[_actor(o, args.actor_key)].append(str(o.get("true_stage", "NORMAL")))

    out_dir = Path(args.out) / args.population / args.phase
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for actor, events in obs_by_actor.items():
        (out_dir / f"{actor}.ndjson").write_text("\n".join(json.dumps(e) for e in events) + "\n")
        stages = stages_by_actor.get(actor, ["NORMAL"] * len(events))
        labels = {"actor_id": actor,
                  "is_attack": any(s != "NORMAL" for s in stages),
                  "true_stages": stages[:len(events)] or ["NORMAL"] * len(events)}
        (out_dir / f"{actor}.labels.json").write_text(json.dumps(labels) + "\n")
        n += 1
    print(f"STAGED {n} actors -> {out_dir}")


if __name__ == "__main__":
    main()
