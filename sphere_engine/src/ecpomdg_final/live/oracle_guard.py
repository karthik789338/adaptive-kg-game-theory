from __future__ import annotations
from typing import Any

FORBIDDEN_DEFENDER_FIELDS = {
    "true_stage", "hidden_stage", "true_target", "attacker_profile",
    "redirect_success", "random_draw", "outcome", "physical_effect_future",
}


def assert_defender_visible(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_DEFENDER_FIELDS:
                raise ValueError(f"Oracle field leaked into defender input: {key}")
            assert_defender_visible(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_defender_visible(item)
