"""Create a consistent SQLite backup; never replace an existing backup."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .config import DATA_ROOT, DATABASE_PATH


def backup_database(source: Path, target: Path) -> dict:
    source = source.resolve(strict=True)
    target = target.resolve(strict=False)
    if source == target or target.exists():
        raise FileExistsError("backup target must be new and separate from source")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as reader:
            with sqlite3.connect(target) as backup:
                reader.backup(backup)
                result = backup.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise sqlite3.DatabaseError(f"backup integrity check: {result}")
                table_count = backup.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        return {"path": str(target), "integrity": result, "table_count": table_count,
                "bytes": target.stat().st_size}
    except Exception:
        target.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="Consistent SQLite backup")
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(backup_database(DATABASE_PATH, args.target))


if __name__ == "__main__":
    main()
