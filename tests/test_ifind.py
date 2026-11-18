import json

import pytest
from fastapi.testclient import TestClient

from scripts import credential_settings, ifind
import server


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.content = json.dumps(payload).encode()

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class Session:
    def __init__(self, history):
        self.history = history
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("get_access_token"):
            return Response({"errorcode": 0, "data": {"access_token": "temporary"}})
        return Response(self.history)


def test_ifind_index_history_requires_explicit_symbol_and_marks_return_type_unverified():
    session = Session({"errorcode": 0, "tables": [{"thscode": "000300.SH",
                       "time": ["2026-11-17"], "table": {"close": [4700.25]}}]})
    result = ifind.fetch_index_history("H00300", "000300.SH", "20261117", "20261118",
                                       session=session, refresh_token="private-refresh")
    assert result.rows == [{"tradeDate": "20261117", "indexCode": "H00300", "closeValue": 4700.25}]
    assert result.request["return_type"] == "UNKNOWN"
    assert result.price_basis == "INDEX_CLOSE_UNVERIFIED_RETURN_TYPE"
    assert result.raw_sha256
    assert session.calls[0][1]["headers"]["refresh_token"] == "private-refresh"
    assert session.calls[1][1]["headers"]["access_token"] == "temporary"
    assert session.calls[1][1]["json"]["functionpara"] == {"Interval": "D", "CPS": "no", "Fill": "Omit"}
    assert "private-refresh" not in str(result)
    with pytest.raises(ValueError, match="required"):
        ifind.fetch_index_history("H00300", "", "20261117", "20261118")


def test_ifind_credential_check_exchanges_token_without_returning_it(monkeypatch):
    used = []
    monkeypatch.setattr(ifind, "access_token", lambda value: used.append(value) or "temporary")
    result = credential_settings.test_credential("ifind", environ={"IFIND_REFRESH_TOKEN": "private-refresh"})
    assert used == ["private-refresh"]
    assert result["remote_verified"] is True
    assert result["ok"] is True
    assert "private-refresh" not in str(result)


def test_ifind_local_api_returns_candidates_without_secrets(monkeypatch):
    session = Session({"errorcode": 0, "tables": [{"thscode": "000300.SH",
                       "time": ["2026-11-17"], "table": {"close": [4700.25]}}]})
    monkeypatch.setattr(server, "fetch_ifind_index_history", lambda *args: ifind.fetch_index_history(
        *args, session=session, refresh_token="private-refresh"))
    response = TestClient(server.app).post("/api/ifind/index-history", json={
        "index_code": "H00300", "ifind_code": "000300.SH",
        "start_date": "20261117", "end_date": "20261118"})
    assert response.status_code == 200
    assert response.json()["rows"][0]["closeValue"] == 4700.25
    assert response.json()["priceBasis"] == "INDEX_CLOSE_UNVERIFIED_RETURN_TYPE"
    assert "private-refresh" not in response.text
    assert "temporary" not in response.text


@pytest.mark.parametrize("payload", [
    {"errorcode": -1, "errmsg": "private-refresh"},
    {"errorcode": 0, "tables": [{"thscode": "000300.SH", "time": ["2026-11-17"], "table": {"close": [0]}}]},
    {"errorcode": 0, "tables": [{"thscode": "999999.SH", "time": ["2026-11-17"], "table": {"close": [1.0]}}]},
])
def test_ifind_rejects_failed_or_invalid_history_without_echoing_secret(payload):
    with pytest.raises((RuntimeError, ValueError)) as error:
        ifind.fetch_index_history("H00300", "000300.SH", "20261117", "20261118",
                                  session=Session(payload), refresh_token="private-refresh")
    assert "private-refresh" not in str(error.value)
