"""Baseline defender policies for the LIVE H1 comparison on SPHERE.

These drive the same live UserSpaceActionGate your belief-conditioned policy
drives. Each `decide(view)` returns a defender action NAME (string); the live
driver converts it to your DefenderAction enum. They read only the public view
(belief, public status, previous action, step, MAP stage) -- never hidden state.

Decision points in the live flow:
  step 4 = post-enumeration (after connection->session->GI->reads)
  step 5 = post-select (after the fresh real SELECT is observed)

BELIEF_ADAPTIVE is your existing BeliefConditionedMultiStageDefenderPolicy; the
driver uses that class directly. These three are the H1 baselines.
"""
from __future__ import annotations

ACTIONS = ("MONITOR", "ACTIVATE_DECOY", "REDIRECT", "CONTAIN")


def _belief(view):
    return dict(getattr(view, "belief", {}) or {})


def _status(view):
    return getattr(view, "status", None)


class MonitorOnlyPolicy:
    """Negative control: never acts."""
    name = "MONITOR_ONLY"

    def decide(self, view) -> str:
        return "MONITOR"


class FixedSchedulePolicy:
    """Stage-agnostic fixed schedule: arm the decoy at the enumeration step and
    redirect at the select step, unconditionally (no belief, no stage estimate).
    """
    name = "FIXED_SCHEDULE"

    def __init__(self, activate_step: int = 4, redirect_step: int = 5):
        self.activate_step = activate_step
        self.redirect_step = redirect_step

    def decide(self, view) -> str:
        st = _status(view)
        budget = getattr(st, "defense_budget_remaining", 0)
        decoy = getattr(st, "decoy_active", False)
        step = getattr(view, "step_index", 0)
        if not decoy and step <= self.activate_step and budget >= 1:
            return "ACTIVATE_DECOY"
        if decoy and step >= self.redirect_step and budget >= 1:
            return "REDIRECT"
        return "MONITOR"


class StageAgnosticReactivePolicy:
    """Reacts only to the current MAP stage estimate (no full posterior reasoning)."""
    name = "STAGE_AGNOSTIC"

    def decide(self, view) -> str:
        st = _status(view)
        budget = getattr(st, "defense_budget_remaining", 0)
        decoy = getattr(st, "decoy_active", False)
        contained = getattr(st, "real_controller_contained", False)
        stage = getattr(view, "map_stage", "")
        if not decoy and stage == "DER_ENUMERATION" and budget >= 1:
            return "ACTIVATE_DECOY"
        if decoy and stage in ("CONTROL_MANIPULATION", "PHYSICAL_IMPACT") and budget >= 1:
            return "REDIRECT"
        if stage == "PHYSICAL_IMPACT" and budget >= 2 and not contained:
            return "CONTAIN"
        return "MONITOR"


def get_baseline(name: str):
    return {"MONITOR_ONLY": MonitorOnlyPolicy, "FIXED_SCHEDULE": FixedSchedulePolicy,
            "STAGE_AGNOSTIC": StageAgnosticReactivePolicy}[name]()
