"""Resolve and verify a published snapshot on either host platform."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


DATASETS = {"etf": "etf_prices.json", "index": "index_prices.json"}


def resolve_file(data_root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", relative):
        raise ValueError("invalid snapshot path")
    parts = relative.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid snapshot path")
    root = data_root.resolve()
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root):
        raise ValueError("invalid snapshot path")
    return path


def read_manifest(data_root: Path) -> dict:
    path = data_root / "current_manifest.json"
    if not path.exists():
        return {"snapshot_id": "legacy", "status": "legacy", "files": DATASETS.copy()}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("snapshot_id"), str) or not isinstance(manifest.get("files"), dict):
        raise ValueError("invalid snapshot manifest")
    for key in DATASETS:
        resolve_file(data_root, manifest["files"][key])
    return manifest


def read_dataset(data_root: Path, manifest: dict, key: str) -> dict:
    if key not in DATASETS:
        raise ValueError("unknown dataset")
    path = resolve_file(data_root, manifest["files"][key])
    raw = path.read_bytes()
    digest = manifest.get("sha256", {}).get(key)
    if digest and hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("snapshot hash mismatch")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("invalid snapshot structure")
    if (key == "etf" and "strategies" in payload) or (key == "index" and "products" in payload):
        raise ValueError("manifest points to wrong dataset")
    if manifest["snapshot_id"] != "legacy" and payload.get("snapshot_id") != manifest["snapshot_id"]:
        raise ValueError("snapshot version mismatch")
    return payload
