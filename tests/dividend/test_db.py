from scripts.dividend.db import add_watchlist, connect, init_schema, list_watchlist, upsert_security


def test_schema_is_additive_and_watchlist_is_idempotent(tmp_path):
    path = tmp_path / "dividend.db"
    init_schema(path)
    upsert_security(path, {"security_id": "ETF:510880", "code": "510880", "name": "红利ETF", "market": "SH", "security_type": "ETF", "aliases": "红利"})
    add_watchlist(path, "ETF:510880")
    add_watchlist(path, "ETF:510880")
    assert [row["security_id"] for row in list_watchlist(path, "ETF")] == ["ETF:510880"]


def test_source_documents_are_hash_deduplicated(tmp_path):
    path = tmp_path / "dividend.db"
    init_schema(path)
    with connect(path) as db:
        first = db.execute("INSERT INTO source_documents(source_id, title, url, sha256) VALUES (?,?,?,?)", ("s1", "公告", "https://example.test/a", "abc")).lastrowid
        db.commit()
        second = db.execute("SELECT id FROM source_documents WHERE sha256=?", ("abc",)).fetchone()[0]
    assert first == second
