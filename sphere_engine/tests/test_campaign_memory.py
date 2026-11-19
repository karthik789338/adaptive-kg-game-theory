import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ecpomdg_final.campaign_memory import (
    CampaignMemory, PRIOR_UNKNOWN, PRIOR_BENIGN, PRIOR_ATTACK_EARLY, PRIOR_ATTACK_LATE,
)


def test_unknown_actor_returns_unknown():
    m = CampaignMemory()
    assert m.prior_campaign("nobody", asof=2.0) == PRIOR_UNKNOWN


def test_asof_cutoff_excludes_future_and_self():
    m = CampaignMemory()
    m.record_campaign("a", True, "CONTROL", asof=2.0)
    # A decision at asof=2.0 must NOT see a record stamped at 2.0 (strict <).
    assert m.prior_campaign("a", asof=2.0) == PRIOR_UNKNOWN
    assert m.prior_campaign("a", asof=3.0) == PRIOR_ATTACK_LATE


def test_benign_actor_recorded_benign():
    m = CampaignMemory()
    m.record_campaign("op", False, "NORMAL", asof=1.0)
    assert m.prior_campaign("op", asof=2.0) == PRIOR_BENIGN


def test_early_vs_late_attack():
    m = CampaignMemory()
    m.record_campaign("x", True, "ACCESS", asof=1.0)
    assert m.prior_campaign("x", asof=2.0) == PRIOR_ATTACK_EARLY
    m.record_campaign("y", True, "IMPACT", asof=1.0)
    assert m.prior_campaign("y", asof=2.0) == PRIOR_ATTACK_LATE


def test_json_roundtrip(tmp_path):
    m = CampaignMemory()
    m.record_campaign("a", True, "CONTROL", asof=1.0)
    p = tmp_path / "store.json"
    m.save_json(p)
    loaded = CampaignMemory.load_json(p)
    assert loaded.prior_campaign("a", asof=2.0) == PRIOR_ATTACK_LATE


def test_dynamic_feature_only_in_dynamic_mode():
    from ecpomdg_final.offline_kg import OfflineKG, EpisodeRuntimeGraph
    from ecpomdg_final.simulator import featurize
    from ecpomdg_final.types import KnowledgeMode
    m = CampaignMemory()
    m.record_campaign("atk-1", True, "IMPACT", asof=1.0)
    ev = {"event_type": "GENERAL_INTERROGATION", "protocol_phase": "NONE", "target_role": "REAL",
          "asset_id": "controller-real", "source_host": "attacker", "actor_id": "atk-1", "physical_alarm": "NO"}
    obs = featurize(ev, OfflineKG(), EpisodeRuntimeGraph(), KnowledgeMode.DYNAMIC_KG, memory=m, asof=2.0)
    assert obs.kg_prior_campaign == PRIOR_ATTACK_LATE
    assert "kg_prior_campaign" in obs.features(KnowledgeMode.DYNAMIC_KG)
    assert "kg_prior_campaign" not in obs.features(KnowledgeMode.STATIC_KG)
    assert "kg_prior_campaign" not in obs.features(KnowledgeMode.TELEMETRY_ONLY)
