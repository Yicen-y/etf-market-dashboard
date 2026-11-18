import sqlite3

import pytest

from scripts.backup_db import backup_database
from scripts.storage_audit import inventory


def test_sqlite_wal_backup_restores_and_cleanup_is_preview(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    source = data / "market.db"
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE prices(day TEXT PRIMARY KEY, close REAL)")
    writer.execute("INSERT INTO prices VALUES ('2026-11-12', 100.5)")
    writer.commit()
    target = data / "backups" / "market-copy.db"
    result = backup_database(source, target)
    assert result["integrity"] == "ok"
    with sqlite3.connect(target) as restored:
        assert restored.execute("SELECT close FROM prices").fetchone()[0] == 100.5
    with pytest.raises(FileExistsError):
        backup_database(source, target)
    assert target.exists()
    assert inventory(data)["cleanup_preview_only"] is not None
    writer.close()
