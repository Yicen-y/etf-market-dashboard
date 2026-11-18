"""Windows local release backup, preflight, and explicit rollback.

Run with the local API and scheduled updater stopped. The rollback keeps newer
immutable release files and restores the backup's database and active pointer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

from .backup_db import backup_database
from .snapshot import read_dataset, read_manifest, resolve_file


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(data_dir: Path, *, include_legacy: bool = False) -> dict:
    data_dir = data_dir.resolve(strict=True)
    database = data_dir / "etf_market.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"database integrity: {integrity}")
    manifest = read_manifest(data_dir)
    if manifest["snapshot_id"] == "legacy":
        raise ValueError("versioned manifest required")
    for key in ("etf", "index"):
        read_dataset(data_dir, manifest, key)
    names = ["etf_market.db", "current_manifest.json"]
    if include_legacy:
        names.extend(("etf_prices.json", "index_prices.json"))
    names.extend(manifest["files"][key] for key in ("etf", "index"))
    files = {name: _sha(resolve_file(data_dir, name)) for name in names}
    return {"snapshot_id": manifest["snapshot_id"], "integrity": integrity, "files": files}


def prepare(data_dir: Path, backup_dir: Path) -> dict:
    data_dir = data_dir.resolve(strict=True)
    backup_dir = backup_dir.resolve(strict=False)
    if backup_dir.exists() or backup_dir.is_relative_to(data_dir):
        raise ValueError("backup directory must be new and outside the data directory")
    current = inspect(data_dir)
    backup_dir.mkdir(parents=True)
    try:
        backup_database(data_dir / "etf_market.db", backup_dir / "etf_market.db")
        for name in current["files"]:
            if name == "etf_market.db":
                continue
            destination = resolve_file(backup_dir, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolve_file(data_dir, name), destination)
        sealed = inspect(backup_dir)
        if sealed["snapshot_id"] != current["snapshot_id"] or any(
                sealed["files"][name] != digest for name, digest in current["files"].items()
                if name != "etf_market.db"):
            raise ValueError("source changed during backup; retry with updater stopped")
        (backup_dir / "backup_inventory.json").write_text(
            json.dumps(sealed, ensure_ascii=False, indent=2), encoding="utf-8")
        return sealed
    except Exception:
        # Keep a failed backup for diagnosis; it is never accepted without an inventory.
        raise


def rollback(data_dir: Path, backup_dir: Path, expected_current: str) -> dict:
    data_dir = data_dir.resolve(strict=True)
    backup_dir = backup_dir.resolve(strict=True)
    if backup_dir.is_relative_to(data_dir) or data_dir == backup_dir:
        raise ValueError("backup must be outside the live data directory")
    inventory_path = backup_dir / "backup_inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    legacy_names = tuple(name for name in ("etf_prices.json", "index_prices.json") if name in inventory["files"])
    source = inspect(backup_dir, include_legacy=bool(legacy_names))
    if source != inventory:
        raise ValueError("backup inventory or files changed")
    current = read_manifest(data_dir)
    if current["snapshot_id"] != expected_current:
        raise ValueError("active snapshot changed; rollback aborted")
    database = data_dir / "etf_market.db"
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise RuntimeError("SQLite sidecar exists; stop local API and updater, then retry")

    def replace_from_backup(name: str) -> None:
        source_file = resolve_file(backup_dir, name)
        target_file = resolve_file(data_dir, name)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_file.with_name(target_file.name + ".rollback.tmp")
        shutil.copy2(source_file, temporary)
        if _sha(temporary) != inventory["files"][name]:
            temporary.unlink(missing_ok=True)
            raise ValueError("rollback copy hash mismatch")
        os.replace(temporary, target_file)

    # Restore referenced immutable files before the pointer, and the database
    # before the pointer too. Local readers must remain stopped during this step.
    for name in inventory["files"]:
        if name not in {"etf_market.db", "current_manifest.json", "etf_prices.json", "index_prices.json"}:
            target = resolve_file(data_dir, name)
            if target.exists() and _sha(target) != inventory["files"][name]:
                raise ValueError("immutable release file differs from backup")
            if not target.exists():
                replace_from_backup(name)
    for name in ("etf_market.db", *legacy_names, "current_manifest.json"):
        replace_from_backup(name)
    restored = inspect(data_dir, include_legacy=bool(legacy_names))
    if restored != inventory:
        raise ValueError("rollback completed but final inventory differs")
    return restored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "preflight", "rollback"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--expected-current")
    args = parser.parse_args()
    if args.mode == "prepare":
        if not args.backup_dir:
            parser.error("prepare requires --backup-dir")
        result = prepare(args.data_dir, args.backup_dir)
    elif args.mode == "preflight":
        result = inspect(args.data_dir)
    else:
        if not args.backup_dir or not args.expected_current:
            parser.error("rollback requires --backup-dir and --expected-current")
        result = rollback(args.data_dir, args.backup_dir, args.expected_current)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
