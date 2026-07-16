"""Problem protocol and objective-weight configuration."""
from dataclasses import dataclass

PROBLEM_PROTOCOL = "paper-exp-v3-pod-size-height-no-mix-partial-bbc"

@dataclass(frozen=True)
class MasterWeights:
    x: float = 0.0
    concentration: float = 10.0

@dataclass(frozen=True)
class SubWeights:
    dist: float = 16.0
    balance: float = 24.0
    conflict: float = 42.0

@dataclass(frozen=True)
class Weights:
    master: MasterWeights = MasterWeights()
    sub: SubWeights = SubWeights()
    objective_scale: float = 1000.0
