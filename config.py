from dataclasses import dataclass

@dataclass(frozen=True)
class MasterWeights:
    """Weights for Master Problem objective terms."""
    x: float = 8.0          # normalized open-bay-time penalty
    concentration: float = 10.0  # normalized joint ship-group block excess

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
