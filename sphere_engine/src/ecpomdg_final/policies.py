from __future__ import annotations
from dataclasses import dataclass

from .types import DefenderAction, DefenderView


class MonitorOnlyPolicy:
    def decide(self, view: DefenderView) -> DefenderAction:
        return DefenderAction.MONITOR


@dataclass
class FixedSchedulePolicy:
    """Stage-agnostic schedule. It never reads the posterior."""
    activate_turn: int = 2
    redirect_turn: int = 4
    contain_turn: int = 6

    def decide(self, view: DefenderView) -> DefenderAction:
        if view.turn == self.activate_turn and not view.public_state.decoy_active:
            return DefenderAction.ACTIVATE_DECOY
        if view.turn == self.redirect_turn and view.public_state.decoy_active:
            return DefenderAction.REDIRECT
        if view.turn == self.contain_turn:
            return DefenderAction.CONTAIN
        return DefenderAction.MONITOR


@dataclass
class StageAgnosticReactivePolicy:
    """Uses current alarm/event severity but no posterior or stage estimate."""
    def decide(self, view: DefenderView) -> DefenderAction:
        event = view.observation.event_type
        if event in {"IEC104_SESSION", "GENERAL_INTERROGATION"} and not view.public_state.decoy_active:
            return DefenderAction.ACTIVATE_DECOY
        if event == "CONTROL_SELECT" and view.public_state.decoy_active:
            return DefenderAction.REDIRECT
        if event == "CONTROL_EXECUTE" or view.observation.physical_alarm == "YES":
            return DefenderAction.CONTAIN
        return DefenderAction.MONITOR


@dataclass
class BeliefAdaptivePolicy:
    """Belief-conditioned defender for the six-state (NORMAL + 5) filter.

    It deploys cheap deception as soon as it believes an attack is present
    (low P(NORMAL)) — early enough to catch the redirect window — but stays in
    MONITOR when belief rests in NORMAL, so quiet operations cost nothing. The
    expensive CONTAIN is reserved for high late-stage belief.
    """
    activate_threshold: float = 0.50   # on P(attack) = 1 - P(NORMAL)
    redirect_threshold: float = 0.35   # on P(CONTROL)
    contain_threshold: float = 0.55    # on P(CONTROL)+P(IMPACT)

    def decide(self, view: DefenderView) -> DefenderAction:
        b = view.belief
        attack_belief = 1.0 - float(b.get("NORMAL", 0.0))
        late_risk = float(b.get("CONTROL", 0.0)) + float(b.get("IMPACT", 0.0))
        ps = view.public_state

        if late_risk >= self.contain_threshold and ps.budget_remaining >= 2:
            if view.previous_action == DefenderAction.REDIRECT.value or float(b.get("IMPACT", 0.0)) >= 0.25:
                return DefenderAction.CONTAIN
        if ps.decoy_active and float(b.get("CONTROL", 0.0)) >= self.redirect_threshold:
            if ps.budget_remaining >= 1:
                return DefenderAction.REDIRECT
        if not ps.decoy_active and attack_belief >= self.activate_threshold:
            if ps.budget_remaining >= 1:
                return DefenderAction.ACTIVATE_DECOY
        return DefenderAction.MONITOR
