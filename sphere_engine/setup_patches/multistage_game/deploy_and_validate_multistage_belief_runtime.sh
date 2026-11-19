#!/usr/bin/env bash

set -euo pipefail
set -o pipefail

ROOT="$HOME/ecpomdg"
PKG="$ROOT/ec_pomdg"
CONFIG="$ROOT/configs"

SETUP="$HOME/ecpomdg_setup/multistage_game"
AUDIT="$HOME/ecpomdg_audit/multistage_game"

mkdir -p \
  "$PKG" \
  "$CONFIG" \
  "$SETUP" \
  "$AUDIT"


echo "================================================================"
echo " EC-POMDG FIVE-STAGE BELIEF RUNTIME"
echo "================================================================"


# ================================================================
# 1. VERIFY PREVIOUS FROZEN ENGINE
# ================================================================

echo
echo "===== VERIFY FROZEN PHASE-4B ENGINE ====="

sha256sum \
  -c \
  "$HOME/ecpomdg_audit/ecpomdg_runtime/sphere_ecpomdg_compatibility_engine_sha256.txt"

echo \
  "FROZEN_PHASE4B_ENGINE_INTEGRITY: PASS"


# ================================================================
# 2. FIVE-STAGE BAYES MODEL CONFIGURATION
# ================================================================

cat > \
"$CONFIG/multistage_attack_belief_model.json" <<'JSON'
{
  "schema_version": 1,

  "stages": [
    "RECONNAISSANCE",
    "ACCESS",
    "DER_ENUMERATION",
    "CONTROL_MANIPULATION",
    "PHYSICAL_IMPACT"
  ],

  "initial_belief": [
    0.78,
    0.12,
    0.06,
    0.03,
    0.01
  ],

  "transition_models": {
    "MONITOR": [
      [0.78, 0.22, 0.00, 0.00, 0.00],
      [0.00, 0.70, 0.30, 0.00, 0.00],
      [0.00, 0.00, 0.68, 0.32, 0.00],
      [0.00, 0.00, 0.00, 0.62, 0.38],
      [0.00, 0.00, 0.00, 0.00, 1.00]
    ],

    "ACTIVATE_DECOY": [
      [0.78, 0.22, 0.00, 0.00, 0.00],
      [0.00, 0.70, 0.30, 0.00, 0.00],
      [0.00, 0.00, 0.68, 0.32, 0.00],
      [0.00, 0.00, 0.00, 0.62, 0.38],
      [0.00, 0.00, 0.00, 0.00, 1.00]
    ],

    "REDIRECT": [
      [0.78, 0.22, 0.00, 0.00, 0.00],
      [0.00, 0.70, 0.30, 0.00, 0.00],
      [0.00, 0.00, 0.68, 0.32, 0.00],
      [0.00, 0.00, 0.00, 0.62, 0.38],
      [0.00, 0.00, 0.00, 0.00, 1.00]
    ],

    "CONTAIN": [
      [0.90, 0.10, 0.00, 0.00, 0.00],
      [0.00, 0.90, 0.10, 0.00, 0.00],
      [0.00, 0.00, 0.90, 0.10, 0.00],
      [0.00, 0.00, 0.00, 0.90, 0.10],
      [0.00, 0.00, 0.00, 0.00, 1.00]
    ]
  },

  "evidence": {
    "NO_ACTIVITY": {
      "canonical_stage": "RECONNAISSANCE",
      "base_likelihood": [0.65, 0.45, 0.30, 0.18, 0.10],
      "static_kg_affinity": [1.00, 1.00, 1.00, 1.00, 1.00]
    },

    "NETWORK_RECON": {
      "canonical_stage": "RECONNAISSANCE",
      "base_likelihood": [0.90, 0.35, 0.20, 0.08, 0.03],
      "static_kg_affinity": [1.80, 1.00, 1.00, 1.00, 1.00]
    },

    "IEC104_SESSION_ESTABLISHED": {
      "canonical_stage": "ACCESS",
      "base_likelihood": [0.35, 0.90, 0.40, 0.15, 0.05],
      "static_kg_affinity": [1.00, 1.80, 1.00, 1.00, 1.00]
    },

    "IEC104_INTERROGATION": {
      "canonical_stage": "DER_ENUMERATION",
      "base_likelihood": [0.65, 0.55, 0.85, 0.30, 0.08],
      "static_kg_affinity": [1.20, 1.00, 1.80, 1.00, 1.00]
    },

    "DER_POINT_ENUMERATION": {
      "canonical_stage": "DER_ENUMERATION",
      "base_likelihood": [0.20, 0.45, 0.92, 0.35, 0.08],
      "static_kg_affinity": [1.00, 1.00, 2.00, 1.00, 1.00]
    },

    "CONTROL_SELECT": {
      "canonical_stage": "CONTROL_MANIPULATION",
      "base_likelihood": [0.08, 0.15, 0.35, 0.90, 0.25],
      "static_kg_affinity": [1.00, 1.00, 1.00, 1.80, 1.00]
    },

    "CONTROL_EXECUTE_REAL": {
      "canonical_stage": "CONTROL_MANIPULATION",
      "base_likelihood": [0.05, 0.12, 0.30, 0.95, 0.35],
      "static_kg_affinity": [1.00, 1.00, 1.00, 2.00, 1.00]
    },

    "CONTROL_EXECUTE_DECOY": {
      "canonical_stage": "CONTROL_MANIPULATION",
      "base_likelihood": [0.05, 0.12, 0.30, 0.95, 0.10],
      "static_kg_affinity": [1.00, 1.00, 1.00, 2.00, 1.00]
    },

    "PHYSICAL_EFFECT": {
      "canonical_stage": "PHYSICAL_IMPACT",
      "base_likelihood": [0.01, 0.04, 0.10, 0.45, 0.98],
      "static_kg_affinity": [1.00, 1.00, 1.00, 1.00, 2.20]
    }
  },

  "dynamic_overlay": {
    "evidence_count_bonus_per_observation": 0.10,
    "temporal_consistency_bonus": 1.20
  }
}
JSON


# ================================================================
# 3. MULTI-STAGE BELIEF RUNTIME
# ================================================================

cat > \
"$PKG/multistage_attack_belief_runtime.py" <<'PY'
import json
import math

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from .phase2a_game_contract import (
    DefenderAction,
)


class AttackStage(str, Enum):
    RECONNAISSANCE = "RECONNAISSANCE"
    ACCESS = "ACCESS"
    DER_ENUMERATION = "DER_ENUMERATION"
    CONTROL_MANIPULATION = "CONTROL_MANIPULATION"
    PHYSICAL_IMPACT = "PHYSICAL_IMPACT"


class StageEvidence(str, Enum):
    NO_ACTIVITY = "NO_ACTIVITY"
    NETWORK_RECON = "NETWORK_RECON"
    IEC104_SESSION_ESTABLISHED = "IEC104_SESSION_ESTABLISHED"
    IEC104_INTERROGATION = "IEC104_INTERROGATION"
    DER_POINT_ENUMERATION = "DER_POINT_ENUMERATION"
    CONTROL_SELECT = "CONTROL_SELECT"
    CONTROL_EXECUTE_REAL = "CONTROL_EXECUTE_REAL"
    CONTROL_EXECUTE_DECOY = "CONTROL_EXECUTE_DECOY"
    PHYSICAL_EFFECT = "PHYSICAL_EFFECT"


class KnowledgeMode(str, Enum):
    NO_KG = "NO_KG"
    STATIC_KG = "STATIC_KG"
    DYNAMIC_KG = "DYNAMIC_KG"


@dataclass(frozen=True)
class BeliefUpdate:
    evidence: str
    defender_action: str
    mode: str
    predictive_prior: Dict[str, float]
    observation_likelihood: Dict[str, float]
    posterior: Dict[str, float]
    map_stage: str
    map_probability: float
    entropy_bits: float


class EpisodeKnowledgeOverlay:
    """
    Episode-local evidence overlay.

    It never mutates any frozen source KG.
    """

    def __init__(
        self,
        stages: List[str],
        count_bonus: float,
        temporal_bonus: float,
    ):
        self.stages = list(stages)

        self.count_bonus = float(
            count_bonus
        )

        self.temporal_bonus = float(
            temporal_bonus
        )

        self.nodes = []
        self.edges = []

        self.stage_evidence_counts = {
            stage: 0
            for stage in self.stages
        }

        self.last_node_id = None
        self.last_canonical_stage = None


    def register(
        self,
        evidence: str,
        canonical_stage: str,
    ) -> Dict[str, float]:

        previous_stage = (
            self.last_canonical_stage
        )

        node_id = (
            f"evidence-{len(self.nodes) + 1:04d}"
        )

        node = {
            "node_id":
                node_id,

            "evidence":
                evidence,

            "canonical_stage":
                canonical_stage,

            "sequence_index":
                len(self.nodes),
        }

        self.nodes.append(
            node
        )


        if self.last_node_id is not None:

            self.edges.append({
                "source":
                    self.last_node_id,

                "target":
                    node_id,

                "relation":
                    "TEMPORALLY_PRECEDES",
            })


        self.stage_evidence_counts[
            canonical_stage
        ] += 1


        multipliers = {
            stage: 1.0
            for stage in self.stages
        }


        count = (
            self.stage_evidence_counts[
                canonical_stage
            ]
        )


        multipliers[
            canonical_stage
        ] *= (
            1.0
            + self.count_bonus
            * count
        )


        if previous_stage is not None:

            previous_index = (
                self.stages.index(
                    previous_stage
                )
            )

            current_index = (
                self.stages.index(
                    canonical_stage
                )
            )

            temporally_consistent = (
                current_index
                >= previous_index
                and
                current_index
                - previous_index
                <= 1
            )

            if temporally_consistent:

                multipliers[
                    canonical_stage
                ] *= (
                    self.temporal_bonus
                )


        self.last_node_id = (
            node_id
        )

        self.last_canonical_stage = (
            canonical_stage
        )


        return multipliers


    def snapshot(
        self,
    ):

        return {
            "nodes":
                list(
                    self.nodes
                ),

            "edges":
                list(
                    self.edges
                ),

            "stage_evidence_counts":
                dict(
                    self.stage_evidence_counts
                ),
        }


class MultiStageBeliefUpdater:

    def __init__(
        self,
        mode: KnowledgeMode,
        config_path: Optional[str] = None,
    ):

        if isinstance(
            mode,
            str,
        ):
            mode = (
                KnowledgeMode(
                    mode
                )
            )

        self.mode = mode


        if config_path is None:

            config_path = (
                Path.home()
                / "ecpomdg"
                / "configs"
                / "multistage_attack_belief_model.json"
            )


        self.config = json.loads(
            Path(
                config_path
            ).read_text(
                encoding="utf-8"
            )
        )


        self.stages = (
            self.config[
                "stages"
            ]
        )


        expected = [
            stage.value
            for stage
            in AttackStage
        ]

        if (
            self.stages
            != expected
        ):

            raise ValueError(
                "Stage contract mismatch"
            )


        self._validate_model()


        dynamic = (
            self.config[
                "dynamic_overlay"
            ]
        )


        self.overlay = (
            EpisodeKnowledgeOverlay(
                stages=
                    self.stages,

                count_bonus=
                    dynamic[
                        "evidence_count_bonus_per_observation"
                    ],

                temporal_bonus=
                    dynamic[
                        "temporal_consistency_bonus"
                    ],
            )
            if
            self.mode
            == KnowledgeMode.DYNAMIC_KG
            else None
        )


    def _validate_model(
        self,
    ):

        prior = (
            self.config[
                "initial_belief"
            ]
        )

        if len(prior) != 5:

            raise ValueError(
                "Initial belief must have five stages"
            )

        if not math.isclose(
            sum(prior),
            1.0,
            abs_tol=1e-12,
        ):

            raise ValueError(
                "Initial belief is not normalized"
            )


        transition_models = (
            self.config[
                "transition_models"
            ]
        )


        for action in DefenderAction:

            matrix = (
                transition_models[
                    action.value
                ]
            )

            if (
                len(matrix)
                != 5
            ):

                raise ValueError(
                    action.value
                )

            for row in matrix:

                if (
                    len(row)
                    != 5
                ):

                    raise ValueError(
                        action.value
                    )

                if not math.isclose(
                    sum(row),
                    1.0,
                    abs_tol=1e-12,
                ):

                    raise ValueError(
                        "Transition row is not normalized"
                    )


        evidence_model = (
            self.config[
                "evidence"
            ]
        )


        for evidence in StageEvidence:

            item = (
                evidence_model[
                    evidence.value
                ]
            )

            if (
                len(
                    item[
                        "base_likelihood"
                    ]
                )
                != 5
            ):

                raise ValueError(
                    evidence.value
                )

            if (
                len(
                    item[
                        "static_kg_affinity"
                    ]
                )
                != 5
            ):

                raise ValueError(
                    evidence.value
                )


    def initial_belief(
        self,
    ) -> Dict[str, float]:

        return {
            stage: float(
                probability
            )

            for (
                stage,
                probability,
            )
            in zip(
                self.stages,
                self.config[
                    "initial_belief"
                ],
            )
        }


    def predict(
        self,
        belief: Dict[str, float],
        defender_action: DefenderAction,
    ) -> Dict[str, float]:

        if isinstance(
            defender_action,
            str,
        ):
            defender_action = (
                DefenderAction(
                    defender_action
                )
            )


        vector = [
            float(
                belief[
                    stage
                ]
            )
            for stage
            in self.stages
        ]


        total = sum(
            vector
        )

        if not math.isclose(
            total,
            1.0,
            abs_tol=1e-9,
        ):

            raise ValueError(
                "Belief must be normalized"
            )


        matrix = (
            self.config[
                "transition_models"
            ][
                defender_action.value
            ]
        )


        prediction = []

        for next_stage in range(5):

            value = sum(
                vector[
                    previous_stage
                ]
                *
                matrix[
                    previous_stage
                ][
                    next_stage
                ]

                for previous_stage
                in range(5)
            )

            prediction.append(
                value
            )


        return {
            stage: prediction[index]

            for (
                index,
                stage,
            )
            in enumerate(
                self.stages
            )
        }


    def update(
        self,
        belief: Dict[str, float],
        evidence: StageEvidence,
        defender_action: DefenderAction,
    ) -> BeliefUpdate:

        if isinstance(
            evidence,
            str,
        ):
            evidence = (
                StageEvidence(
                    evidence
                )
            )


        if isinstance(
            defender_action,
            str,
        ):
            defender_action = (
                DefenderAction(
                    defender_action
                )
            )


        predictive = (
            self.predict(
                belief,
                defender_action,
            )
        )


        model = (
            self.config[
                "evidence"
            ][
                evidence.value
            ]
        )


        base = list(
            model[
                "base_likelihood"
            ]
        )


        affinity = list(
            model[
                "static_kg_affinity"
            ]
        )


        dynamic_multiplier = {
            stage: 1.0
            for stage in self.stages
        }


        if (
            self.mode
            == KnowledgeMode.DYNAMIC_KG
        ):

            dynamic_multiplier = (
                self.overlay.register(
                    evidence=
                        evidence.value,

                    canonical_stage=
                        model[
                            "canonical_stage"
                        ],
                )
            )


        likelihood = {}


        for (
            index,
            stage,
        ) in enumerate(
            self.stages
        ):

            value = float(
                base[
                    index
                ]
            )


            if self.mode in {
                KnowledgeMode.STATIC_KG,
                KnowledgeMode.DYNAMIC_KG,
            }:

                value *= float(
                    affinity[
                        index
                    ]
                )


            if (
                self.mode
                == KnowledgeMode.DYNAMIC_KG
            ):

                value *= (
                    dynamic_multiplier[
                        stage
                    ]
                )


            likelihood[
                stage
            ] = value


        unnormalized = {
            stage:
                predictive[
                    stage
                ]
                *
                likelihood[
                    stage
                ]

            for stage in self.stages
        }


        denominator = sum(
            unnormalized.values()
        )


        if denominator <= 0:

            raise RuntimeError(
                "Bayesian normalization denominator is zero"
            )


        posterior = {
            stage:
                unnormalized[
                    stage
                ]
                / denominator

            for stage in self.stages
        }


        map_stage = max(
            self.stages,
            key=lambda stage:
                posterior[
                    stage
                ],
        )


        entropy = -sum(
            probability
            * math.log2(
                probability
            )

            for probability
            in posterior.values()
            if probability > 0
        )


        return BeliefUpdate(
            evidence=
                evidence.value,

            defender_action=
                defender_action.value,

            mode=
                self.mode.value,

            predictive_prior=
                predictive,

            observation_likelihood=
                likelihood,

            posterior=
                posterior,

            map_stage=
                map_stage,

            map_probability=
                posterior[
                    map_stage
                ],

            entropy_bits=
                entropy,
        )
PY


# ================================================================
# 4. VALIDATOR
# ================================================================

cat > \
"$SETUP/validate_multistage_attack_belief_runtime.py" <<'PY'
#!/usr/bin/env python3

import inspect
import json
import math
from pathlib import Path

from ec_pomdg.phase2a_game_contract import (
    DefenderAction,
)

from ec_pomdg.multistage_attack_belief_runtime import (
    AttackStage,
    StageEvidence,
    KnowledgeMode,
    MultiStageBeliefUpdater,
)


AUDIT = (
    Path.home()
    / "ecpomdg_audit"
    / "multistage_game"
)

RESULT = (
    AUDIT
    / "multistage_attack_belief_runtime_validation.json"
)


# ================================================================
# CONTRACT
# ================================================================

expected_stages = [
    "RECONNAISSANCE",
    "ACCESS",
    "DER_ENUMERATION",
    "CONTROL_MANIPULATION",
    "PHYSICAL_IMPACT",
]


assert [
    stage.value
    for stage in AttackStage
] == expected_stages


print(
    "FIVE_STAGE_ATTACK_CONTRACT: PASS"
)


# ================================================================
# BAYES API MUST NOT ACCEPT TRUE HIDDEN STATE
# ================================================================

parameters = list(
    inspect.signature(
        MultiStageBeliefUpdater.update
    ).parameters
)


assert parameters == [
    "self",
    "belief",
    "evidence",
    "defender_action",
]


print(
    "BELIEF_UPDATE_HIDDEN_STATE_INDEPENDENCE: PASS"
)


# ================================================================
# RUN SAME EVIDENCE THROUGH THREE KNOWLEDGE MODES
# ================================================================

sequence = [
    StageEvidence.NETWORK_RECON,
    StageEvidence.IEC104_SESSION_ESTABLISHED,
    StageEvidence.DER_POINT_ENUMERATION,
    StageEvidence.CONTROL_EXECUTE_REAL,
    StageEvidence.PHYSICAL_EFFECT,
]


expected_map = [
    "RECONNAISSANCE",
    "ACCESS",
    "DER_ENUMERATION",
    "CONTROL_MANIPULATION",
    "PHYSICAL_IMPACT",
]


mode_results = {}


for mode in (
    KnowledgeMode.NO_KG,
    KnowledgeMode.STATIC_KG,
    KnowledgeMode.DYNAMIC_KG,
):

    updater = (
        MultiStageBeliefUpdater(
            mode=mode
        )
    )

    belief = (
        updater.initial_belief()
    )

    records = []


    for evidence in sequence:

        result = (
            updater.update(
                belief=
                    belief,

                evidence=
                    evidence,

                defender_action=
                    DefenderAction.MONITOR,
            )
        )

        belief = dict(
            result.posterior
        )

        records.append({
            "evidence":
                evidence.value,

            "map_stage":
                result.map_stage,

            "map_probability":
                result.map_probability,

            "entropy_bits":
                result.entropy_bits,

            "posterior":
                result.posterior,
        })


    mode_results[
        mode.value
    ] = {
        "records":
            records,

        "final_belief":
            belief,

        "overlay":
            (
                updater.overlay.snapshot()
                if updater.overlay
                else None
            ),
    }


    print()
    print(
        mode.value
    )

    for row in records:

        print(
            " ",
            row[
                "evidence"
            ],
            "->",
            row[
                "map_stage"
            ],
            f"{row['map_probability']:.4f}",
        )


# ================================================================
# STATIC/DYNAMIC MUST RESOLVE THE FIVE-STAGE SEQUENCE
# ================================================================

for mode in (
    "STATIC_KG",
    "DYNAMIC_KG",
):

    observed_map = [
        row[
            "map_stage"
        ]

        for row in mode_results[
            mode
        ][
            "records"
        ]
    ]

    assert (
        observed_map
        == expected_map
    )


print()
print(
    "STATIC_KG_STAGE_SEQUENCE_RESOLUTION: PASS"
)

print(
    "DYNAMIC_KG_STAGE_SEQUENCE_RESOLUTION: PASS"
)


# ================================================================
# DYNAMIC TEMPORAL OVERLAY
# ================================================================

overlay = (
    mode_results[
        "DYNAMIC_KG"
    ][
        "overlay"
    ]
)


assert (
    len(
        overlay[
            "nodes"
        ]
    )
    == 5
)

assert (
    len(
        overlay[
            "edges"
        ]
    )
    == 4
)


assert all(
    edge[
        "relation"
    ]
    == "TEMPORALLY_PRECEDES"

    for edge in overlay[
        "edges"
    ]
)


print(
    "EPISODE_LOCAL_DYNAMIC_KG_OVERLAY: PASS"
)

print(
    "TEMPORAL_EVIDENCE_CORRELATION: PASS"
)


# ================================================================
# DYNAMIC CONFIDENCE CHECK
# ================================================================

static_impact = (
    mode_results[
        "STATIC_KG"
    ][
        "final_belief"
    ][
        "PHYSICAL_IMPACT"
    ]
)

dynamic_impact = (
    mode_results[
        "DYNAMIC_KG"
    ][
        "final_belief"
    ][
        "PHYSICAL_IMPACT"
    ]
)


assert (
    dynamic_impact
    >
    static_impact
)


print(
    "DYNAMIC_TEMPORAL_CONFIDENCE_GAIN: PASS"
)


# ================================================================
# DECOY CONTROL MUST NOT CREATE PHYSICAL-IMPACT EVIDENCE
# ================================================================

updater = (
    MultiStageBeliefUpdater(
        mode=
            KnowledgeMode.DYNAMIC_KG
    )
)

belief = (
    updater.initial_belief()
)


decoy_sequence = [
    StageEvidence.NETWORK_RECON,
    StageEvidence.IEC104_SESSION_ESTABLISHED,
    StageEvidence.DER_POINT_ENUMERATION,
    StageEvidence.CONTROL_EXECUTE_DECOY,
]


last = None


for evidence in decoy_sequence:

    last = updater.update(
        belief=
            belief,

        evidence=
            evidence,

        defender_action=
            DefenderAction.MONITOR,
    )

    belief = dict(
        last.posterior
    )


assert (
    last.map_stage
    == "CONTROL_MANIPULATION"
)


print(
    "DECOY_CONTROL_NOT_PHYSICAL_IMPACT: PASS"
)


# ================================================================
# CONTAINMENT MUST REDUCE ONE-STEP FORWARD PROGRESSION
# ================================================================

updater = (
    MultiStageBeliefUpdater(
        mode=
            KnowledgeMode.NO_KG
    )
)


pure_access = {
    "RECONNAISSANCE": 0.0,
    "ACCESS": 1.0,
    "DER_ENUMERATION": 0.0,
    "CONTROL_MANIPULATION": 0.0,
    "PHYSICAL_IMPACT": 0.0,
}


monitor_prediction = (
    updater.predict(
        pure_access,
        DefenderAction.MONITOR,
    )
)


contain_prediction = (
    updater.predict(
        pure_access,
        DefenderAction.CONTAIN,
    )
)


assert (
    contain_prediction[
        "DER_ENUMERATION"
    ]
    <
    monitor_prediction[
        "DER_ENUMERATION"
    ]
)


print(
    "DEFENDER_ACTION_CONDITIONED_STAGE_TRANSITION: PASS"
)


# ================================================================
# NORMALIZATION
# ================================================================

for mode in mode_results.values():

    for record in mode[
        "records"
    ]:

        assert math.isclose(
            sum(
                record[
                    "posterior"
                ].values()
            ),
            1.0,
            abs_tol=1e-9,
        )


print(
    "BAYES_POSTERIOR_NORMALIZATION: PASS"
)


# ================================================================
# WRITE VALIDATION ARTIFACT
# ================================================================

AUDIT.mkdir(
    parents=True,
    exist_ok=True,
)


RESULT.write_text(
    json.dumps(
        {
            "schema_version":
                1,

            "five_stage_contract":
                expected_stages,

            "knowledge_modes": [
                "NO_KG",
                "STATIC_KG",
                "DYNAMIC_KG",
            ],

            "validation_sequence": [
                evidence.value
                for evidence
                in sequence
            ],

            "results":
                mode_results,

            "constraints": {
                "true_hidden_stage_provided_to_filter":
                    False,

                "frozen_source_kgs_mutated":
                    False,

                "dynamic_kg_is_episode_local_overlay":
                    True,

                "terminal_outcomes_separate_from_stage_belief":
                    True,
            },
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="ascii",
)


print()
print(
    "MULTISTAGE_ATTACK_BELIEF_RUNTIME_VALIDATION: PASS"
)

print(
    "Result:",
    RESULT
)
PY


# ================================================================
# 5. LOCAL SYNTAX
# ================================================================

echo
echo "===== LOCAL SYNTAX ====="

python3 -m json.tool \
  "$CONFIG/multistage_attack_belief_model.json" \
  >/dev/null

PYTHONPATH="$ROOT" \
python3 -m py_compile \
  "$PKG/multistage_attack_belief_runtime.py" \
  "$SETUP/validate_multistage_attack_belief_runtime.py"

echo \
  "MULTISTAGE_BELIEF_RUNTIME_SOURCE_SYNTAX: PASS"


# ================================================================
# 6. LOCAL VALIDATION
# ================================================================

echo
echo "===== XDC VALIDATION ====="

PYTHONPATH="$ROOT" \
python3 \
  "$SETUP/validate_multistage_attack_belief_runtime.py" \
  | tee \
  "$AUDIT/multistage_attack_belief_runtime_validation.log"


# ================================================================
# 7. DEPLOY TO DEFENDER
# ================================================================

echo
echo "===== DEPLOY TO DEFENDER ====="

ssh defender '
mkdir -p \
  ~/ecpomdg/ec_pomdg \
  ~/ecpomdg/configs \
  ~/ecpomdg/multistage_game
'


# FIX: ship the FULL engine package + configs to the defender. A fresh testbed
# has no ec_pomdg there, but the defender RUNS the belief runtime, so it needs
# phase2a_game_contract, phase4b_*, __init__.py and the kernel config -- not
# just the single runtime module the lines below copy.
scp -r "$PKG"/. defender:~/ecpomdg/ec_pomdg/
scp -r "$CONFIG"/. defender:~/ecpomdg/configs/


scp \
  "$PKG/multistage_attack_belief_runtime.py" \
  defender:~/ecpomdg/ec_pomdg/

scp \
  "$CONFIG/multistage_attack_belief_model.json" \
  defender:~/ecpomdg/configs/

scp \
  "$SETUP/validate_multistage_attack_belief_runtime.py" \
  defender:~/ecpomdg/multistage_game/


echo
echo "===== DEFENDER VALIDATION ====="

ssh defender '
set -euo pipefail

mkdir -p \
  ~/ecpomdg_audit/multistage_game

PYTHONPATH="$HOME/ecpomdg" \
python3 \
  ~/ecpomdg/multistage_game/validate_multistage_attack_belief_runtime.py \
  | tee \
  ~/ecpomdg_audit/multistage_game/multistage_attack_belief_runtime_validation.log
' \
| tee \
"$AUDIT/multistage_attack_belief_runtime_defender_validation.log"


# ================================================================
# 8. FREEZE
# ================================================================

echo
echo "===== FREEZE MULTI-STAGE BELIEF RUNTIME ====="

sha256sum \
  "$CONFIG/multistage_attack_belief_model.json" \
  "$PKG/multistage_attack_belief_runtime.py" \
  "$SETUP/validate_multistage_attack_belief_runtime.py" \
  "$AUDIT/multistage_attack_belief_runtime_validation.json" \
  "$AUDIT/multistage_attack_belief_runtime_validation.log" \
  "$AUDIT/multistage_attack_belief_runtime_defender_validation.log" \
  > \
  "$AUDIT/multistage_attack_belief_runtime_sha256.txt"


cat \
  "$AUDIT/multistage_attack_belief_runtime_sha256.txt"


echo
echo "================================================================"
echo "EC_POMDG_MULTISTAGE_BELIEF_RUNTIME: PASS"
echo "================================================================"

