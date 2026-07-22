import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import config
import experiment_metadata
from experiment_metadata import (
    collect_experiment_metadata,
    collect_git_metadata,
    collect_gurobi_version,
    collect_weight_profile,
    csv_metadata_fields,
    write_experiment_artifacts,
)


class ExperimentMetadataTest(unittest.TestCase):
    @patch("experiment_metadata.subprocess.run")
    def test_git_metadata_clean_and_dirty(self, run):
        run.side_effect = [
            SimpleNamespace(returncode=0, stdout="abc123\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="feature\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        ]
        self.assertEqual(
            collect_git_metadata(),
            {"git_commit": "abc123", "git_branch": "feature", "git_dirty": False},
        )
        self.assertTrue(all(call.kwargs["timeout"] == 2.0 for call in run.mock_calls))

        run.reset_mock()
        run.side_effect = [
            SimpleNamespace(returncode=0, stdout="abc123\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="feature\n", stderr=""),
            SimpleNamespace(returncode=0, stdout=" M file.py\n", stderr=""),
        ]
        self.assertTrue(collect_git_metadata()["git_dirty"])

    @patch("experiment_metadata.subprocess.run", side_effect=FileNotFoundError)
    def test_git_unavailable_is_nonfatal(self, _run):
        self.assertEqual(
            collect_git_metadata(),
            {"git_commit": None, "git_branch": None, "git_dirty": None},
        )

    @patch(
        "experiment_metadata.subprocess.run",
        side_effect=subprocess.TimeoutExpired("git", 2),
    )
    def test_git_timeout_is_nonfatal(self, _run):
        self.assertEqual(
            collect_git_metadata(),
            {"git_commit": None, "git_branch": None, "git_dirty": None},
        )

    def test_gurobi_version_and_unavailable_interface(self):
        available = SimpleNamespace(
            gurobi=SimpleNamespace(version=lambda: (12, 0, 3))
        )
        with patch.object(experiment_metadata, "gp", available):
            self.assertEqual(collect_gurobi_version(), "12.0.3")

        def unavailable():
            raise RuntimeError("version unavailable")

        broken = SimpleNamespace(gurobi=SimpleNamespace(version=unavailable))
        with patch.object(experiment_metadata, "gp", broken):
            self.assertIsNone(collect_gurobi_version())

    def test_manifest_and_csv_share_batch_metadata(self):
        metadata = {
            "git_commit": "abc123",
            "git_branch": "feature",
            "git_dirty": True,
            "problem_protocol": config.PROBLEM_PROTOCOL,
            "python_version": "3.test",
            "python_implementation": "CPython",
            "platform": "test-platform",
            "gurobi_version": "12.0.3",
            "threads": 2,
            "mip_gap": .01,
            "time_limit": 5.0,
            "stability_formulation": "epigraph_only",
            "weight_profile": collect_weight_profile(),
        }
        row = {"instance": "pilot_small", **csv_metadata_fields(metadata), "ok": True}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pilot_results.csv"
            manifest_path = write_experiment_artifacts(
                rows=[row],
                output_csv=output,
                metadata=metadata,
                requested_matrix={"sizes": ["pilot_small"], "mip_gap": .01},
                command=["python", "run_experiments.py"],
                created_at_utc="2026-07-18T10:30:00Z",
            )
            self.assertTrue(output.exists())
            self.assertEqual(
                manifest_path,
                Path(directory) / "pilot_results.manifest.json",
            )
            with output.open(encoding="utf-8-sig", newline="") as stream:
                csv_row = next(csv.DictReader(stream))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(csv_row["git_commit"], manifest["metadata"]["git_commit"])
        self.assertEqual(csv_row["problem_protocol"], config.PROBLEM_PROTOCOL)
        self.assertEqual(int(csv_row["threads"]), 2)
        self.assertEqual(float(csv_row["mip_gap"]), .01)
        self.assertEqual(csv_row["stability_formulation"], "epigraph_only")
        self.assertEqual(manifest["row_count"], 1)
        self.assertEqual(manifest["expected_row_count"], 1)
        self.assertTrue(manifest["complete"])
        self.assertTrue(manifest["all_ok"])
        self.assertEqual(
            csv_row["weight_profile"],
            json.dumps(
                metadata["weight_profile"],
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def test_manifest_treats_csv_false_string_as_failure(self):
        metadata = {
            "git_commit": "abc123",
            "weight_profile": collect_weight_profile(),
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = write_experiment_artifacts(
                rows=[{"ok": "True"}, {"ok": "False"}],
                output_csv=Path(directory) / "partial.csv",
                metadata=metadata,
                requested_matrix={"status": "partial"},
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["row_count"], 2)
        self.assertFalse(manifest["all_ok"])

    def test_manifest_records_incomplete_atomic_checkpoint(self):
        metadata = {"git_commit": "abc123"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "checkpoint.csv"
            manifest_path = write_experiment_artifacts(
                rows=[{"instance": "one", "ok": True}],
                output_csv=output,
                metadata=metadata,
                requested_matrix={"seeds": [1, 2]},
                expected_row_count=2,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            temporary_files = list(Path(directory).glob(".*.tmp"))
        self.assertEqual(manifest["row_count"], 1)
        self.assertEqual(manifest["expected_row_count"], 2)
        self.assertFalse(manifest["complete"])
        self.assertEqual(temporary_files, [])

    def test_collected_metadata_uses_runtime_configuration(self):
        with patch(
            "experiment_metadata.collect_git_metadata",
            return_value={
                "git_commit": None,
                "git_branch": None,
                "git_dirty": None,
            },
        ), patch(
            "experiment_metadata.collect_gurobi_version",
            return_value=None,
        ):
            metadata = collect_experiment_metadata(
                threads=3,
                mip_gap=.02,
                time_limit=7,
            )
        self.assertEqual(metadata["problem_protocol"], config.PROBLEM_PROTOCOL)
        self.assertEqual(metadata["threads"], 3)
        self.assertEqual(metadata["mip_gap"], .02)
        self.assertEqual(metadata["time_limit"], 7.0)
        self.assertIn(metadata["stability_formulation"], ("epigraph_only", "exact_big_m"))

    def test_dependency_sensitivity_profile_is_recorded(self):
        profile = collect_weight_profile("conservative")
        dependency = profile["dependency"]
        self.assertEqual(dependency["profile"], "conservative")
        self.assertEqual(dependency["trigger_mode"], "shortage_repair_only")
        self.assertEqual(
            dependency["edge_threshold"],
            config.DEPENDENCY_PROFILES["conservative"]["edge_threshold"],
        )
        self.assertEqual(
            dependency["path_threshold"],
            config.DEPENDENCY_PROFILES["conservative"]["path_threshold"],
        )


if __name__ == "__main__":
    unittest.main()
