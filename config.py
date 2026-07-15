from dataclasses import dataclass

PROBLEM_PROTOCOL = "paper-exp-v3-pod-size-height-no-mix-partial-bbc"

@dataclass(frozen=True)
class MasterWeights:
    """Weights for Master Problem objective terms."""
    x: float = 0.0          # legacy compatibility; activation is derived, not optimized
    concentration: float = 10.0  # normalized joint ship-group bay usage

@dataclass(frozen=True)
class SubWeights:
    """Weights for Subproblem objective terms."""
    dist: float = 16.0       # normalized berth-to-block distance term
    balance: float = 24.0    # normalized L1 block-flow balance term
    conflict: float = 42.0   # normalized outbound-pressure conflict term

@dataclass(frozen=True)
class Weights:
    master: MasterWeights = MasterWeights()
    sub: SubWeights = SubWeights()
    objective_scale: float = 1000.0
