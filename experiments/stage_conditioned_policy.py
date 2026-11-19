#!/usr/bin/env python3
"""
Stage-conditioned defender policy for the DEPLOYED EC-POMDG engine.

Drop this into the same place as run_experiments.py (it imports from `ec_pomdg`,
exactly like run_experiments.py does). It gives the defender a lever at EVERY
kill-chain stage instead of only at the control window, which is what fills the
two currently-empty stages (RECON, ACCESS) in the game tree.

Stage is tracked by decision index, which matches the fixed attacker sequence
run_experiments.py drives:
    i=1 NETWORK_RECON (RECON)     -> DECEPTIVE_SURFACE
    i=2 ESTABLISH_ACCESS (ACCESS) -> SESSION_CHALLENGE
    i=3 ENUMERATE_DER (DER_ENUM)  -> HONEY_POINTS (+ ACTIVATE_DECOY)
    i>=4 SELECT/EXECUTE (CONTROL/IMPACT) -> defer to the belief-conditioned core
         (REDIRECT in the control window; SAFETY_INTERLOCK as last resort)

REQUIRES the engine changes described in STAGE_CONDITIONED_ENGINE_PATCH.md:
the four new DefenderAction members and their transition/observation handling,
plus the CONTAINED_SAFE terminal. Until those exist, the new actions fall back
to MONITOR inside the engine and this policy degrades to the base behaviour.

Budget note: stage-conditioned defense is defense-in-depth, so run it at
budget >= 6 (see the budget sweep in run_experiments_extended.py). The policy
RESERVES budget for the control bundle (arm + redirect) so early deception can
never starve the main divert lever.
"""
from __future__ import annotations

from ec_pomdg.phase2a_game_contract import DefenderAction
from ec_pomdg.belief_conditioned_multistage_defender_policy import (
    BeliefConditionedMultiStageDefenderPolicy,
)


def _has(name: str) -> bool:
    return hasattr(DefenderAction, name)


class StageConditionedDefenderPolicy:
    """Belief-conditioned core + a stage-appropriate action at every stage."""

    def __init__(self):
        self.i = 0
        self._core = BeliefConditionedMultiStageDefenderPolicy()

    def decide(self, view):
        self.i += 1
        s = view.status
        budget = s.defense_budget_remaining

        # Reserve budget for the control bundle so early deception never starves
        # the decoy+redirect divert lever (the single highest-value action).
        reserve = (0 if s.decoy_active else 1) + 1  # arm (if not armed) + redirect

        # --- STAGE 1: RECON -------------------------------------------------
        if self.i == 1 and _has("DECEPTIVE_SURFACE") and budget - 1 >= reserve:
            return DefenderAction.DECEPTIVE_SURFACE

        # --- STAGE 2: ACCESS ------------------------------------------------
        if self.i == 2 and _has("SESSION_CHALLENGE") and budget - 1 >= reserve:
            return DefenderAction.SESSION_CHALLENGE

        # --- STAGE 3: DER_ENUM : honey-bait, then arm the decoy -------------
        if self.i == 3:
            if _has("HONEY_POINTS") and budget - 1 >= reserve:
                return DefenderAction.HONEY_POINTS
            if not s.decoy_active and budget >= 1:
                return DefenderAction.ACTIVATE_DECOY

        # --- STAGE 4-5: CONTROL / PHYSICAL ---------------------------------
        # Defer to the deployed belief-conditioned policy for the redirect
        # window and the containment fallback. If the engine exposes the
        # SAFETY_INTERLOCK action and the attacker has reached the impact
        # window with no decoy diversion, prefer the hard safety stop.
        core_action = self._core.decide(view)
        if (_has("SAFETY_INTERLOCK")
                and self.i >= 5
                and core_action in (DefenderAction.MONITOR, DefenderAction.CONTAIN)
                and budget >= 2):
            return DefenderAction.SAFETY_INTERLOCK
        return core_action
