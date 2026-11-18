from __future__ import annotations
import math
from typing import Iterable, Mapping


def multiclass_brier(posterior: Mapping[str, float], true_stage: str) -> float:
    return sum((float(p) - (1.0 if s == true_stage else 0.0)) ** 2 for s, p in posterior.items())


def stage_log_loss(posterior: Mapping[str, float], true_stage: str) -> float:
    return -math.log(max(1e-15, float(posterior[true_stage])))


def stage_accuracy(posterior: Mapping[str, float], true_stage: str) -> int:
    predicted = max(posterior, key=posterior.get)
    return int(predicted == true_stage)


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else float("nan")
