"""Write a non-destructive SHA-256 inventory for local experiment artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def build_inventory(roots: list[Path], *, label: str) -> dict[str, object]:
    root_pairs = [
        (root.as_posix().rstrip("/"), root.resolve())
        for root in roots
    ]
    resolved_roots = [resolved for _display, resolved in root_pairs]
    missing = [str(root) for root in resolved_roots if not root.is_dir()]
    if missing:
        raise FileNotFoundError(f"inventory roots do not exist: {missing}")

    records: list[dict[str, object]] = []
    root_summaries: list[dict[str, object]] = []
    aggregate = hashlib.sha256()
    for display_root, root in root_pairs:
        root_records: list[dict[str, object]] = []
        for path in sorted(
            (item for item in root.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(root).as_posix(),
        ):
            stat = path.stat()
            relative_path = path.relative_to(root).as_posix()
            digest = sha256_file(path)
            record = {
                "root": display_root,
                "relative_path": relative_path,
                "bytes": stat.st_size,
                "modified_utc": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "sha256": digest,
            }
            canonical = (
                f"{display_root}\0{relative_path}\0{stat.st_size}\0{digest}\n"
            )
            aggregate.update(canonical.encode("utf-8"))
            records.append(record)
            root_records.append(record)
        root_summaries.append({
            "path": display_root,
            "file_count": len(root_records),
            "total_bytes": sum(int(item["bytes"]) for item in root_records),
        })

    return {
        "schema": "local-result-archive-inventory-v1",
        "label": label,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_branch": git_value("branch", "--show-current"),
        "git_describe": git_value("describe", "--always", "--tags", "--dirty"),
        "aggregate_sha256": aggregate.hexdigest(),
        "file_count": len(records),
        "total_bytes": sum(int(item["bytes"]) for item in records),
        "roots": root_summaries,
        "files": records,
    }


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    for root in args.root:
        resolved = root.resolve()
        if output == resolved or resolved in output.parents:
            parser.error("output must be outside every inventoried root")

    payload = build_inventory(args.root, label=args.label)
    write_json_atomic(output, payload)
    print(
        json.dumps(
            {
                "output": output.as_posix(),
                "file_count": payload["file_count"],
                "total_bytes": payload["total_bytes"],
                "aggregate_sha256": payload["aggregate_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
