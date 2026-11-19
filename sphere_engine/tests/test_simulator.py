import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ecpomdg_final.offline_kg import OfflineKG, EpisodeRuntimeGraph
from ecpomdg_final.simulator import SimConfig, generate_inference_episode, featurize
from ecpomdg_final.types import AttackerProfile, KnowledgeMode

FORBIDDEN = {"true_stage", "is_benign_evaluator_only", "stage", "target"}


def test_paired_seed_reproducible():
    a = generate_inference_episode(5, AttackerProfile.CAUTIOUS, SimConfig())
    b = generate_inference_episode(5, AttackerProfile.CAUTIOUS, SimConfig())
    assert a == b


def test_raw_event_has_no_oracle_fields():
    ep = generate_inference_episode(5, AttackerProfile.PERSISTENT, SimConfig())
    for turn in ep:
        assert FORBIDDEN.isdisjoint(turn["raw_event"].keys())


def test_telemetry_mode_hides_kg_features():
    kg = OfflineKG()
    rt = EpisodeRuntimeGraph()
    ep = generate_inference_episode(5, AttackerProfile.CAUTIOUS, SimConfig())
    obs = featurize(ep[2]["raw_event"], kg, rt, KnowledgeMode.DYNAMIC_KG)
    assert "kg_topology_risk" not in obs.features(KnowledgeMode.TELEMETRY_ONLY)
    assert "kg_topology_risk" in obs.features(KnowledgeMode.STATIC_KG)
    assert "kg_path_continuity" not in obs.features(KnowledgeMode.STATIC_KG)
    assert "kg_path_continuity" in obs.features(KnowledgeMode.DYNAMIC_KG)


def test_attack_free_episode_labels_normal():
    ep = generate_inference_episode(5, AttackerProfile.CAUTIOUS, SimConfig(), has_attacker=False)
    assert all(t["true_stage"] == "NORMAL" for t in ep)


def test_dynamic_continuity_uses_only_past():
    # The runtime chain for a source must not include the current event's own
    # technique when continuity is read (pre-decision discipline).
    kg = OfflineKG()
    rt = EpisodeRuntimeGraph()
    e1 = {"event_type": "NETWORK_RECON", "protocol_phase": "NONE", "target_role": "SCADA",
          "asset_id": "scada-hmi", "source_host": "attacker", "physical_alarm": "NO"}
    ctx1 = kg.context_for(e1, rt, "DYNAMIC_KG")
    assert ctx1.path_continuity == "SPARSE"  # nothing seen before this event
