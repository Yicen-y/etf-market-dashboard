import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client():
    return TestClient(server.app)


def test_get_credentials_returns_status_only(client, monkeypatch):
    monkeypatch.setattr(
        server.credential_settings,
        "list_credential_status",
        lambda: [
            {"provider": "wind_mcp", "configured": True, "masked": "****"},
            {"provider": "htbr_etf", "configured": False, "masked": ""},
            {"provider": "etfirst", "configured": True, "masked": "****"},
        ],
    )

    response = client.get("/api/settings/credentials")

    assert response.status_code == 200
    assert response.json() == {
        "credentials": [
            {"provider": "wind_mcp", "configured": True, "masked": "****"},
            {"provider": "htbr_etf", "configured": False, "masked": ""},
            {"provider": "etfirst", "configured": True, "masked": "****"},
        ]
    }
    assert "secret" not in response.text


def test_put_credential_saves_key_but_never_returns_it(client, monkeypatch):
    observed = {}

    def save(provider, value):
        observed["provider"] = provider
        observed["value"] = value

    monkeypatch.setattr(server.credential_settings, "set_credential", save)

    response = client.put(
        "/api/settings/credentials/wind_mcp",
        json={"key": "secret-value"},
    )

    assert response.status_code == 200
    assert observed == {"provider": "wind_mcp", "value": "secret-value"}
    assert response.json() == {"provider": "wind_mcp", "configured": True}
    assert "secret-value" not in response.text


def test_delete_credential_returns_unconfigured_status(client, monkeypatch):
    observed = []
    monkeypatch.setattr(
        server.credential_settings,
        "delete_credential",
        lambda provider: observed.append(provider),
    )

    response = client.delete("/api/settings/credentials/etfirst")

    assert response.status_code == 200
    assert observed == ["etfirst"]
    assert response.json() == {"provider": "etfirst", "configured": False}


def test_test_credential_returns_provider_result_without_secret(client, monkeypatch):
    monkeypatch.setattr(
        server.credential_settings,
        "test_credential",
        lambda provider: {
            "provider": provider,
            "configured": True,
            "ok": False,
            "remote_verified": False,
            "status": "not_verified",
            "message": "本地配置检查通过；未验证远程服务",
        },
    )

    response = client.post("/api/settings/credentials/htbr_etf/test")

    assert response.status_code == 502
    assert response.json()["detail"]["provider"] == "htbr_etf"
    assert response.json()["detail"]["status"] == "not_verified"
    assert "secret" not in response.text


@pytest.mark.parametrize(
    ("method", "url", "payload"),
    [
        ("put", "/api/settings/credentials/unknown", {"key": "secret"}),
        ("delete", "/api/settings/credentials/unknown", None),
        ("post", "/api/settings/credentials/unknown/test", None),
    ],
)
def test_unknown_provider_returns_404(client, method, url, payload):
    response = getattr(client, method)(url, json=payload) if payload else getattr(client, method)(url)
    assert response.status_code == 404


def test_empty_key_returns_400_without_calling_storage(client, monkeypatch):
    called = []
    monkeypatch.setattr(
        server.credential_settings,
        "set_credential",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    response = client.put("/api/settings/credentials/wind_mcp", json={"key": "  "})

    assert response.status_code == 400
    assert called == []


def test_provider_test_failure_returns_502_and_safe_message(client, monkeypatch):
    monkeypatch.setattr(
        server.credential_settings,
        "test_credential",
        lambda provider: {
            "provider": provider,
            "configured": True,
            "ok": False,
            "remote_verified": False,
            "status": "check_failed",
            "message": "连接失败",
        },
    )

    response = client.post("/api/settings/credentials/wind_mcp/test")

    assert response.status_code == 502
    assert response.json()["detail"]["status"] == "check_failed"
    assert "secret" not in response.text


def test_successful_provider_test_returns_200(client, monkeypatch):
    monkeypatch.setattr(
        server.credential_settings,
        "test_credential",
        lambda provider: {
            "provider": provider,
            "configured": True,
            "ok": True,
            "remote_verified": True,
            "status": "remote_verified",
            "message": "连接成功",
        },
    )

    response = client.post("/api/settings/credentials/wind_mcp/test")

    assert response.status_code == 200
    assert response.json()["status"] == "remote_verified"
