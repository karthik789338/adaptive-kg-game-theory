#!/usr/bin/env python3
"""Offline smoke test: pipeline wiring + reproducibility, not a hypothesis test.

Verifies paired-seed determinism, posterior normalisation, the six-state belief
filter's NORMAL hypothesis on attack-free traffic, and that no evaluator-only
field reaches a defender observation. It does NOT establish H1 or H2 -- use the
experiment runners for that.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecpomdg_final.dbn import CategoricalStageDBN
from ecpomdg_final.offline_kg import OfflineKG, EpisodeRuntimeGraph
from ecpomdg_final.simulator import SimConfig, generate_inference_episode, featurize
from ecpomdg_final.types import AttackerProfile, KnowledgeMode
from ecpomdg_final.provenance import write_manifest

SIX_STATES = ["NORMAL", "RECON", "ACCESS", "DER_ENUM", "CONTROL", "IMPACT"]
config = SimConfig()


def featurized(seed, profile, has_attacker):
    kg = OfflineKG()
    rt = EpisodeRuntimeGraph()
    raw = generate_inference_episode(seed, profile, config, has_attacker=has_attacker)
    return [{"true_stage": t["true_stage"],
             "observation": featurize(t["raw_event"], kg, rt, KnowledgeMode.DYNAMIC_KG)} for t in raw]


# 1. Paired-seed determinism: identical raw episodes for identical seeds.
a = generate_inference_episode(27, AttackerProfile.PERSISTENT, config)
b = generate_inference_episode(27, AttackerProfile.PERSISTENT, config)
assert a == b, "paired-seed reproducibility failed"

# 2. Train a six-state DYNAMIC filter on mixed data; posterior must normalise.
train = [featurized(s, "CAUTIOUS", s % 2 == 0) for s in range(5001, 5041)]
model = CategoricalStageDBN(KnowledgeMode.DYNAMIC_KG, stages=SIX_STATES).fit(train)
post = model.update(None, train[0][0]["observation"]).posterior
assert abs(sum(post.values()) - 1.0) < 1e-9, "posterior not normalised"

# 3. On an attack-free episode the filter should favour NORMAL on average.
quiet = featurized(777, "CAUTIOUS", False)
posterior = None
normal_mass = []
for row in quiet:
    posterior = model.update(posterior, row["observation"]).posterior
    normal_mass.append(posterior["NORMAL"])
assert sum(normal_mass) / len(normal_mass) > 0.30, "NORMAL belief collapsed on quiet traffic"

# 4. No evaluator-only field is present in any defender observation.
for row in train[0]:
    assert not hasattr(row["observation"], "true_stage"), "oracle field on observation"

summary = {
    "paired_seed_reproducible": True,
    "posterior_normalised": True,
    "mean_normal_belief_on_quiet": sum(normal_mass) / len(normal_mass),
    "selected_states": SIX_STATES,
}
out = ROOT / "results" / "offline_smoke.json"
out.write_text(json.dumps(summary, indent=2) + "\n")
write_manifest(ROOT, ROOT / "results" / "provenance_manifest.json")
print(json.dumps(summary, indent=2))
print("OFFLINE_SMOKE: PASS")
print(f"RESULT: {out}")
