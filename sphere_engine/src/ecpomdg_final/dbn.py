from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import log
from typing import Iterable, Mapping, Sequence

import numpy as np

from .types import KnowledgeMode, Observation, Stage, STAGE_ORDER


@dataclass(frozen=True)
class PosteriorResult:
    posterior: dict[str, float]
    map_stage: str
    map_probability: float
    entropy_bits: float


class CategoricalStageDBN:
    """A transparent first-order DBN/HMM-style Bayesian stage filter.

    Transition and categorical emission CPDs are fit from evaluator-labelled
    training traces. At inference time the object consumes only defender-visible
    observations and the previous posterior.
    """

    def __init__(self, mode: KnowledgeMode, alpha: float = 1.0, stages: Sequence[str] | None = None):
        self.mode = KnowledgeMode(mode)
        self.alpha = float(alpha)
        # Default: the five attack stages. H1 passes a six-state list with a
        # leading NORMAL (no-attack) hypothesis so belief can stay put when no
        # adversary is present; H2 uses the five-stage inference-given-attack set.
        self.stage_names = list(stages) if stages is not None else [s.value for s in STAGE_ORDER]
        self._stage_index = {s: i for i, s in enumerate(self.stage_names)}
        self.initial = np.full(len(self.stage_names), 1.0 / len(self.stage_names))
        self.transition = np.full((len(self.stage_names), len(self.stage_names)), 1.0 / len(self.stage_names))
        self.feature_values: dict[str, set[str]] = defaultdict(set)
        self.emission_counts: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        self.stage_feature_totals: dict[str, Counter[str]] = defaultdict(Counter)
        self.temperature = 1.0
        self.fitted = False

    def fit(self, episodes: Sequence[Sequence[Mapping]]) -> "CategoricalStageDBN":
        start = Counter()
        transitions = defaultdict(Counter)
        stage_counts = Counter()

        for episode in episodes:
            previous = None
            for row in episode:
                stage = str(row["true_stage"])
                if stage not in self._stage_index:
                    raise ValueError(f"Unknown stage in training data: {stage}")
                if previous is None:
                    start[stage] += 1
                else:
                    transitions[previous][stage] += 1
                previous = stage
                stage_counts[stage] += 1

                obs = row["observation"]
                if isinstance(obs, Observation) or hasattr(obs, "features"):
                    features = obs.features(self.mode)
                else:
                    features = Observation(**obs).features(self.mode)
                for feature, value in features.items():
                    value = str(value)
                    self.feature_values[feature].add(value)
                    self.emission_counts[stage][feature][value] += 1
                    self.stage_feature_totals[stage][feature] += 1

        n = len(self.stage_names)
        self.initial = np.array([
            start[s] + self.alpha for s in self.stage_names
        ], dtype=float)
        self.initial /= self.initial.sum()

        matrix = np.zeros((n, n), dtype=float)
        for s in self.stage_names:
            i = self._stage_index[s]
            allowed = self.stage_names[i:]  # stage cannot move backwards
            denom = sum(transitions[s][t] for t in allowed) + self.alpha * len(allowed)
            for t in self.stage_names:
                j = self._stage_index[t]
                if j < i:
                    matrix[i, j] = 0.0
                else:
                    matrix[i, j] = (transitions[s][t] + self.alpha) / denom
        self.transition = matrix
        self.fitted = True
        return self

    def _emission_probability(self, stage: str, feature: str, value: str) -> float:
        vocab = self.feature_values.get(feature, set()) | {value}
        denom = self.stage_feature_totals[stage][feature] + self.alpha * max(1, len(vocab))
        return (self.emission_counts[stage][feature][value] + self.alpha) / denom

    def update(self, prior: Mapping[str, float] | None, observation: Observation, temperature: float | None = None) -> PosteriorResult:
        if not self.fitted:
            raise RuntimeError("DBN must be fit before inference")
        tau = float(self.temperature if temperature is None else temperature)
        if prior is None:
            prior_vec = self.initial.copy()
        else:
            prior_vec = np.array([float(prior[s]) for s in self.stage_names], dtype=float)
            prior_vec /= prior_vec.sum()

        predicted = prior_vec @ self.transition
        features = observation.features(self.mode)
        log_weights = np.log(np.clip(predicted, 1e-300, None))
        for i, stage in enumerate(self.stage_names):
            # Temper the emission product (1/tau) to correct naive-Bayes
            # overconfidence from correlated features; tau is selected on a
            # held-out validation split, never on test.
            emission = 0.0
            for feature, value in features.items():
                emission += log(self._emission_probability(stage, feature, str(value)))
            log_weights[i] += emission / tau

        maximum = float(log_weights.max())
        weights = np.exp(log_weights - maximum)
        posterior = weights / weights.sum()
        result = {stage: float(posterior[i]) for i, stage in enumerate(self.stage_names)}
        index = int(np.argmax(posterior))
        entropy = float(-np.sum(np.where(posterior > 0, posterior * np.log2(posterior), 0.0)))
        return PosteriorResult(
            posterior=result,
            map_stage=self.stage_names[index],
            map_probability=float(posterior[index]),
            entropy_bits=entropy,
        )

    def calibrate(self, val_episodes: Sequence[Sequence[Mapping]], grid: Sequence[float] | None = None) -> float:
        """Select the emission temperature minimising mean validation log loss.

        Pure model-calibration step: it reads validation episodes only, never
        the test set, and sets ``self.temperature`` in place.
        """
        grid = list(grid) if grid is not None else [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
        best_tau, best_loss = 1.0, float("inf")
        for tau in grid:
            total, count = 0.0, 0
            for episode in val_episodes:
                posterior = None
                for row in episode:
                    obs = row["observation"]
                    result = self.update(posterior, obs, temperature=tau)
                    posterior = result.posterior
                    total += self.log_loss(posterior, str(row["true_stage"]))
                    count += 1
            mean_loss = total / max(1, count)
            if mean_loss < best_loss:
                best_loss, best_tau = mean_loss, tau
        self.temperature = best_tau
        return best_tau

    def log_loss(self, posterior: Mapping[str, float], true_stage: str) -> float:
        return -log(max(1e-15, float(posterior[true_stage])))
