import json
import tempfile
import unittest
from pathlib import Path

import config
from scripts.freeze_fully_synthetic_formal_indexes import (
    INSTANCE_PROTOCOL,
    load_spec,
    panel_map,
    relative_path,
    select_medium_ordinary,
)


class FullySyntheticIndexFreezeTests(unittest.TestCase):
    def test_matrix_specification_is_complete(self):
        spec = load_spec(
            Path("docs/specs/fully_synthetic_formal_matrix_v1.json")
        )
        self.assertEqual(tuple(spec["formal_seeds"]), config.FORMAL_SEEDS)
        self.assertEqual(spec["counts"]["expected_total_result_rows"], 740)
        self.assertEqual(len(panel_map(spec)), 6)

    def test_medium_ordinary_subset_contains_all_formal_seeds(self):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.json"
            rows = [
                {
                    "profile": "medium_ordinary",
                    "seed": seed,
                    "instance_bundle_filename": f"bundle_{seed}.json",
                }
                for seed in config.FORMAL_SEEDS
            ]
            rows.append({
                "profile": "small_ordinary",
                "seed": config.FORMAL_SEEDS[0],
                "instance_bundle_filename": "unselected.json",
            })
            index.write_text(json.dumps({
                "index_schema": "rolling-instance-index-v1",
                "instance_protocol": INSTANCE_PROTOCOL,
                "experiment_phase": "formal",
                "entry_count": len(rows),
                "entries": rows,
            }), encoding="utf-8")
            entries = select_medium_ordinary(index)
        self.assertEqual(len(entries), 10)
        self.assertEqual({row["seed"] for row in entries}, set(config.FORMAL_SEEDS))

    def test_relative_path_uses_forward_slashes(self):
        value = relative_path(Path("root/derived"), Path("root/source/a.json"))
        self.assertEqual(value, "../source/a.json")
        self.assertNotIn("\\", value)


if __name__ == "__main__":
    unittest.main()
