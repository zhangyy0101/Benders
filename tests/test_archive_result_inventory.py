import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.archive_result_inventory import build_inventory, write_json_atomic


class ArchiveResultInventoryTest(unittest.TestCase):
    def test_inventory_is_sorted_and_content_addressed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "results"
            root.mkdir()
            (root / "z.csv").write_bytes(b"z")
            (root / "a.json").write_bytes(b"a")

            first = build_inventory([root], label="baseline")
            second = build_inventory([root], label="baseline")

            self.assertEqual(
                [item["relative_path"] for item in first["files"]],
                ["a.json", "z.csv"],
            )
            self.assertEqual(first["file_count"], 2)
            self.assertEqual(first["total_bytes"], 2)
            self.assertEqual(first["aggregate_sha256"], second["aggregate_sha256"])
            self.assertEqual(
                first["files"][0]["sha256"], hashlib.sha256(b"a").hexdigest()
            )

    def test_atomic_writer_creates_parseable_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "archive" / "inventory.json"
            write_json_atomic(output, {"schema": "test", "files": []})
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                '{\n  "files": [],\n  "schema": "test"\n}\n',
            )


if __name__ == "__main__":
    unittest.main()
