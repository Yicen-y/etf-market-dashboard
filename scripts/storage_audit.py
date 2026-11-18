"""Read-only inventory and cleanup preview; never deletes market evidence."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

from .config import DATA_PATH
from .snapshot import read_manifest


def inventory(data_root: Path) -> dict:
    root = data_root.resolve()
    try:
        current = read_manifest(root)["snapshot_id"]
    except (OSError, ValueError, KeyError, TypeError):
        current = None
    categories = defaultdict(lambda: {"files": 0, "bytes": 0})
    preview = []
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = [name for name in folders if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            relative = path.relative_to(root)
            parts = relative.parts
            if parts[0] == "raw":
                category = "raw_evidence"
            elif parts[0] == "backups" or name.endswith(".bak"):
                category = "backups"
            elif parts[0] == "releases":
                category = "current_release" if len(parts) > 1 and parts[1] == current else "rollback_releases"
            elif name in ("current_manifest.json", "etf_market.db", "etf_prices.json", "index_prices.json"):
                category = "runtime"
            elif name.endswith(".tmp") or parts[0] in ("cache", "tmp"):
                category = "temporary_preview"
            else:
                category = "other_preserved"
            size = path.stat().st_size
            categories[category]["files"] += 1
            categories[category]["bytes"] += size
            if category == "temporary_preview":
                preview.append({"path": relative.as_posix(), "bytes": size})
    return {"current_snapshot_id": current, "categories": dict(sorted(categories.items())),
            "cleanup_preview_only": sorted(preview, key=lambda row: row["path"]),
            "removed_files": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview disk use without deleting files")
    parser.add_argument("--root", type=Path, default=DATA_PATH.parent)
    args = parser.parse_args()
    print(json.dumps(inventory(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
