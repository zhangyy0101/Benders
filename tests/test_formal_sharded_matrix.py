import csv
import json
import tempfile
import unittest
from pathlib import Path

from config import FORMAL_ORCHESTRATION_PROTOCOL
from run_experiments import experiment_identity
from scripts.run_formal_sharded_matrix import (
    merge_shard_checkpoints,
    partition_instance_entries,
    write_shard_indexes,
)


class FormalShardedMatrixTest(unittest.TestCase):
    def test_budget_balancing_preserves_every_entry_once(self):
        entries = [
            {
                "instance_id": f"I{index}",
                "time_budget_seconds": budget,
            }
            for index, budget in enumerate(
                [20, 20, 60, 60, 120, 120, 120, 60, 20]
            )
        ]
        shards = partition_instance_entries(entries, 2)
        flattened = [
            entry["instance_id"]
            for shard in shards
            for entry in shard
        ]
        loads = [
            sum(entry["time_budget_seconds"] for entry in shard)
            for shard in shards
        ]

        self.assertEqual(sorted(flattened), sorted(
            entry["instance_id"] for entry in entries
        ))
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertLessEqual(abs(loads[0] - loads[1]), 120)

    def test_shard_indexes_are_deterministic_and_relocate_bundles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instances = root / "instances"
            shards = root / "runs" / "main.shards"
            instances.mkdir()
            shards.mkdir(parents=True)
            entries = []
            for index, budget in enumerate((20, 60, 120, 120)):
                bundle = instances / f"I{index}.instance.json"
                bundle.write_text("{}", encoding="utf-8")
                entries.append({
                    "instance_id": f"I{index}",
                    "time_budget_seconds": budget,
                    "instance_bundle_filename": bundle.name,
                })
            source = instances / "index.json"
            source.write_text(json.dumps({
                "index_schema": "rolling-instance-index-v1",
                "instance_protocol": "rolling-formal-instances-v1",
                "experiment_phase": "formal",
                "entry_count": len(entries),
                "entries": entries,
            }), encoding="utf-8")

            first = write_shard_indexes(source, shards, 2)
            first_bytes = [path.read_bytes() for path in first]
            second = write_shard_indexes(source, shards, 2)

            self.assertEqual(first, second)
            self.assertEqual(first_bytes, [path.read_bytes() for path in second])
            for worker, path in enumerate(first):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    payload["formal_orchestration_protocol"],
                    FORMAL_ORCHESTRATION_PROTOCOL,
                )
                self.assertEqual(payload["parallel_shard_index"], worker)
                for entry in payload["entries"]:
                    relocated = (
                        path.parent
                        / entry["instance_bundle_filename"]
                    ).resolve()
                    self.assertTrue(relocated.exists())

    def test_merge_orders_rows_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            rows = [
                {"instance": "I1", "configuration": "core_start", "ok": True},
                {"instance": "I0", "configuration": "core_start", "ok": True},
            ]
            identities = [experiment_identity(row) for row in rows]
            identity_order = {
                identities[1]: (0, 0),
                identities[0]: (1, 0),
            }
            outputs = []
            for worker, row in enumerate(rows):
                output = directory / f"worker-{worker}.csv"
                with output.open("w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerow(row)
                outputs.append(output)

            merged = merge_shard_checkpoints(
                outputs,
                identity_order=identity_order,
                worker_count=2,
            )
            self.assertEqual([row["instance"] for row in merged], ["I0", "I1"])
            self.assertEqual(
                {row["parallel_shard_index"] for row in merged},
                {0, 1},
            )

            with outputs[1].open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerow(rows[0])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                merge_shard_checkpoints(
                    outputs,
                    identity_order=identity_order,
                    worker_count=2,
                )


if __name__ == "__main__":
    unittest.main()
