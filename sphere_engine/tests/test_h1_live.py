import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sphere"))
sys.path.insert(0, str(ROOT / "pipeline"))

from baseline_policies import get_baseline  # noqa: E402

importlib = __import__("importlib")
h1 = importlib.import_module("02_experiment_h1_live")


def _view(stage, decoy, budget, step):
    return NS(belief={"DER_ENUMERATION": 0.6, "CONTROL_MANIPULATION": 0.6, "PHYSICAL_IMPACT": 0.1},
              status=NS(decoy_active=decoy, real_controller_contained=False, defense_budget_remaining=budget),
              map_stage=stage, step_index=step, previous_defender_action="MONITOR")


def test_monitor_only_never_acts():
    assert get_baseline("MONITOR_ONLY").decide(_view("DER_ENUMERATION", False, 4, 4)) == "MONITOR"


def test_fixed_arms_then_redirects():
    assert get_baseline("FIXED_SCHEDULE").decide(_view("RECON", False, 4, 4)) == "ACTIVATE_DECOY"
    assert get_baseline("FIXED_SCHEDULE").decide(_view("CONTROL_MANIPULATION", True, 3, 5)) == "REDIRECT"


def test_stage_agnostic_reacts_to_map_stage():
    assert get_baseline("STAGE_AGNOSTIC").decide(_view("DER_ENUMERATION", False, 4, 4)) == "ACTIVATE_DECOY"
    assert get_baseline("STAGE_AGNOSTIC").decide(_view("CONTROL_MANIPULATION", True, 3, 5)) == "REDIRECT"
    assert get_baseline("STAGE_AGNOSTIC").decide(_view("RECON", False, 4, 4)) == "MONITOR"


def test_aggregate_rates_and_cost():
    records = [
        {"policy": "MONITOR_ONLY", "condition": "attack", "defender_cost": 0, "decoy_diverted": False},
        {"policy": "MONITOR_ONLY", "condition": "benign", "defender_cost": 0, "decoy_diverted": False},
        {"policy": "FIXED_SCHEDULE", "condition": "attack", "defender_cost": 2, "decoy_diverted": True},
        {"policy": "FIXED_SCHEDULE", "condition": "attack", "defender_cost": 2, "decoy_diverted": False},
        {"policy": "FIXED_SCHEDULE", "condition": "benign", "defender_cost": 1, "decoy_diverted": False},
    ]
    agg = h1.aggregate(records)
    assert agg["FIXED_SCHEDULE"]["decoy_diversion_rate"] == 0.5
    assert agg["FIXED_SCHEDULE"]["mean_cost_attack"] == 2.0
    assert agg["FIXED_SCHEDULE"]["mean_wasted_cost_benign"] == 1.0
    assert agg["MONITOR_ONLY"]["decoy_diversion_rate"] == 0.0
