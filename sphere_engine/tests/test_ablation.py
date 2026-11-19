import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from run_experiment_ablation import select, GROUP_FEATURES, MASKS

FEATS_ALL = {
    "base": {"event_type": "CONTROL_SELECT", "protocol_phase": "SELECT", "physical_alarm": "NO"},
    "kg_topology_risk": "HIGH", "kg_source_trust": "UNTRUSTED",
    "kg_ics_stage_hint": "COMMAND_STAGING", "kg_cyber_tactic": "execution",
}


def test_none_is_telemetry_only():
    f = select(FEATS_ALL, "NONE")
    assert set(f) == {"event_type", "protocol_phase", "physical_alarm"}


def test_topology_mask_adds_two_axes():
    f = select(FEATS_ALL, "T")
    assert f["kg_topology_risk"] == "HIGH" and f["kg_source_trust"] == "UNTRUSTED"
    assert "kg_ics_stage_hint" not in f and "kg_cyber_tactic" not in f


def test_full_mask_has_all_groups():
    f = select(FEATS_ALL, "G_I_T")
    for g in GROUP_FEATURES.values():
        for feat in g:
            assert feat in f


def test_all_masks_selectable():
    for m in MASKS:
        assert "event_type" in select(FEATS_ALL, m)
