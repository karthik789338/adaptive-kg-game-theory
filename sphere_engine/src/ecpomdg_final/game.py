from __future__ import annotations
from dataclasses import dataclass
import random
from typing import Callable  # noqa: F401 (reserved for future policy hooks)

from .types import AttackerProfile, DefenderAction, DefenderPublicState, Observation, Stage, STAGE_ORDER
from .simulator import SimConfig, sample_raw_event


ACTION_COST = {
    DefenderAction.MONITOR: 0.0,
    DefenderAction.ACTIVATE_DECOY: 1.0,
    DefenderAction.REDIRECT: 1.0,
    DefenderAction.CONTAIN: 2.0,
}


@dataclass
class GameOutcome:
    compromised_real: bool = False
    diverted_decoy: bool = False
    physical_impact: bool = False
    attacker_blocked: bool = False


class FiveStageMarkovGame:
    """Offline research model used to validate the final experimental pipeline.

    It intentionally avoids the old failure mode where CONTAIN at any early turn
    permanently and costlessly forces attacker withdrawal. Containment is a
    temporary defense state with explicit cost; poorly timed containment can
    expire before the attack reaches control.
    """

    def __init__(self, seed: int, profile: AttackerProfile, budget: int = 4, containment_duration: int = 2, has_attacker: bool = True):
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.profile = AttackerProfile(profile)
        # When False the episode is attack-free: only legitimate operations
        # occur, no stage progression, and no physical impact is possible.
        self.has_attacker = bool(has_attacker)
        self.budget = int(budget)
        self.containment_duration = int(containment_duration)
        self.stage_index = 0
        self.turn = 0
        self.decoy_active = False
        self.containment_turns = 0
        self.defense_cost = 0.0
        self.operational_cost = 0.0
        self.outcome = GameOutcome()
        self.target = "REAL"
        self.done = False
        # Dedicated observation RNG so the ambiguous emission stream is matched
        # across policies at a given seed, independent of defender actions.
        self.obs_rng = random.Random((self.seed ^ 0x9E3779B9) & 0xFFFFFFFF)
        # Separate stream for redirect success so the attacker progression RNG
        # stays aligned across policies that do and do not call REDIRECT.
        self.redirect_rng = random.Random((self.seed ^ 0x5BD1E995) & 0xFFFFFFFF)

    def tick_operational(self, config: SimConfig) -> None:
        """Accrue per-turn operational cost of maintaining active defenses.

        A standing decoy consumes resources and a containment state disrupts
        legitimate control traffic, so holding either is not free. This is what
        gives a belief-conditioned policy room to beat an unconditional fixed
        schedule: act just-in-time rather than early-and-always.
        """
        if self.decoy_active:
            self.operational_cost += config.decoy_hold_cost
        if self.containment_turns > 0:
            self.operational_cost += config.containment_op_penalty

    def observe_raw(self, config: SimConfig) -> dict:
        """Sample one defender-visible raw event from the ambiguous emission model."""
        # Attack-free episodes emit only legitimate operator traffic.
        is_benign = True if not self.has_attacker else (self.obs_rng.random() < config.benign_rate)
        real_impact = self.stage is Stage.IMPACT and self.target == "REAL"
        return sample_raw_event(
            self.stage.value, is_benign, self.obs_rng, config,
            real_impact_fired=real_impact, target=self.target,
        )

    @property
    def stage(self) -> Stage:
        return STAGE_ORDER[self.stage_index]

    def public_state(self) -> DefenderPublicState:
        return DefenderPublicState(
            decoy_active=self.decoy_active,
            containment_turns_remaining=self.containment_turns,
            budget_remaining=self.budget,
            cumulative_defense_cost=self.defense_cost,
        )

    def apply_defender(self, action: DefenderAction) -> None:
        action = DefenderAction(action)
        cost = ACTION_COST[action]
        if cost > self.budget:
            action = DefenderAction.MONITOR
            cost = 0.0
        self.budget -= int(cost)
        self.defense_cost += cost
        if action is DefenderAction.ACTIVATE_DECOY:
            self.decoy_active = True
        elif action is DefenderAction.CONTAIN:
            self.containment_turns = max(self.containment_turns, self.containment_duration)
        elif action is DefenderAction.REDIRECT and self.decoy_active and self.stage in {Stage.ACCESS, Stage.DER_ENUM, Stage.CONTROL}:
            base = 0.72 if self.profile is AttackerProfile.CAUTIOUS else 0.42
            if self.redirect_rng.random() < base:
                self.target = "DECOY"

    def attacker_transition(self) -> None:
        if self.done:
            return
        if not self.has_attacker:
            # No adversary: nothing progresses, no impact can occur.
            self.turn += 1
            return
        # Temporary containment prevents one progression attempt; the attack can retry later.
        if self.containment_turns > 0:
            self.containment_turns -= 1
            self.turn += 1
            return

        if self.stage is Stage.IMPACT:
            if self.target == "DECOY":
                self.outcome.diverted_decoy = True
            else:
                self.outcome.compromised_real = True
                self.outcome.physical_impact = True
            self.done = True
            self.turn += 1
            return

        advance_probability = 0.82 if self.profile is AttackerProfile.PERSISTENT else 0.68
        if self.rng.random() < advance_probability:
            self.stage_index += 1
        self.turn += 1

    def utility(self) -> float:
        value = -self.defense_cost - self.operational_cost
        if self.outcome.physical_impact:
            value -= 100.0
        elif self.outcome.compromised_real:
            value -= 40.0
        if self.outcome.diverted_decoy:
            value += 12.0
        if self.outcome.attacker_blocked:
            value += 5.0
        return value
