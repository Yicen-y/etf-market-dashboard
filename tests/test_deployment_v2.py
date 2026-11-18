import os
import subprocess
import sys
from zipfile import ZipFile

import pytest

from scripts.config import ROOT
from scripts.package_code import package_code


def test_reviewed_corporate_action_seed_is_in_code_package(tmp_path, monkeypatch):
    from scripts.fund_flow.services import corporate_actions
    monkeypatch.setattr(corporate_actions, "DATA_ROOT", tmp_path / "external-data")
    assert corporate_actions.load_seed_action("510310_consolidation").etf_code == "510310.SH"
    package = tmp_path / "code.zip"
    package_code(package)
    with ZipFile(package) as archive:
        assert "scripts/seeds/source_events/510310_consolidation.json" in archive.namelist()


def test_t16_code_package_excludes_runtime_data(tmp_path):
    package = tmp_path / "code.zip"
    names = package_code(package)
    with ZipFile(package) as archive:
        assert names == archive.namelist()
        assert "server.py" in names and "web/index.html" in names
        assert all(not name.startswith("data/") for name in names)
        assert all(not name.endswith((".db", ".bak", ".pyc")) for name in names)


def test_t16_external_data_root_is_used_without_touching_local_runtime(tmp_path):
    root = tmp_path / "persistent"
    root.mkdir()
    script = """from scripts.config import DATA_ROOT, DATABASE_PATH
from scripts.storage import init_reliability_schema, publish_snapshot
from fastapi.testclient import TestClient
init_reliability_schema(DATABASE_PATH)
publish_snapshot(DATA_ROOT, 'server-newer', {'snapshot_id':'server-newer','records':[]}, {'snapshot_id':'server-newer','records':[]})
from server import app
response = TestClient(app).get('/api/snapshot')
assert response.status_code == 200 and response.json()['snapshot_id'] == 'server-newer'
print(DATA_ROOT)
"""
    env = os.environ.copy()
    env["ETF_DATA_DIR"] = str(root)
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "server-newer" in (root / "current_manifest.json").read_text(encoding="utf-8")
