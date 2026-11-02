import json

from scripts.validate_wind import main


def test_list_tools_requires_auth_without_printing_secret(capsys, monkeypatch):
    monkeypatch.delenv("WIND_MCP_AUTH", raising=False)
    assert main(["--list-tools"]) == 2
    output = capsys.readouterr().out
    assert "WIND_MCP_AUTH" in output
    assert "secret" not in output.lower()


def test_report_writer_does_not_serialize_credentials_or_session_ids(tmp_path):
    from scripts.validate_wind import write_report
    report = {"endpoint": "https://example.test/mcp", "results": [{"status": "MATCH", "tradeDate": "20260105"}]}
    path = write_report(report, tmp_path, "json")
    content = path.read_text(encoding="utf-8")
    assert json.loads(content)["results"][0]["status"] == "MATCH"
    assert "Authorization" not in content and "Mcp-Session-Id" not in content


def test_query_refuses_unconfigured_tool_or_schema(capsys, monkeypatch):
    monkeypatch.setenv("WIND_MCP_AUTH", "not-printed")
    assert main(["--codes", "H00300", "--start", "20260101", "--end", "20260131"]) == 2
    assert "--tool" in capsys.readouterr().out
