"""Run the bounded pilot workflow without large or xlarge configurations."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the pilot-small smoke matrix")
    parser.add_argument("--output", default="pilot_smoke_results.csv")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        str(root / "run_experiments.py"),
        "--sizes",
        "pilot_small",
        "--initial-utilizations",
        "0.25",
        "0.70",
        "--forecast-error-modes",
        "multiplicative",
        "booking_add_cancel",
        "--configurations",
        "core_start",
        "full_direct",
        "full",
        "--seeds",
        "0",
        "1",
        "--errors",
        "0.1",
        "--time",
        "5",
        "--output",
        args.output,
    ]
    return subprocess.run(command, cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
