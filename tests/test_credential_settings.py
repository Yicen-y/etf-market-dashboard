import pytest

from scripts import credential_settings, wind_credentials


class FakeKeyring:
    class errors:
        class PasswordDeleteError(Exception):
            pass

    def __init__(self, value=None):
        self.values = {}
        if value is not None:
            self.values[(credential_settings.SERVICE, "WIND_MCP_AUTH")] = value

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


def test_provider_whitelist_and_keyring_account_mapping():
    fake = FakeKeyring()

    validated = credential_settings._test_keyring(fake)
    credential_settings.set_credential("wind_mcp", "wind-secret", keyring_module=validated)
    credential_settings.set_credential("htbr_etf", "htbr-secret", keyring_module=validated)
    credential_settings.set_credential("etfirst", "etfirst-secret", keyring_module=validated)

    assert fake.values[(credential_settings.SERVICE, "WIND_MCP_AUTH")] == "wind-secret"
    assert fake.values[(credential_settings.SERVICE, "HTBR_ETF_API_KEY")] == "htbr-secret"
    assert fake.values[(credential_settings.SERVICE, "ETFIRST_API_KEY")] == "etfirst-secret"
    with pytest.raises(ValueError, match="Unsupported credential provider"):
        credential_settings.set_credential("unknown", "secret", keyring_module=fake)


def test_status_only_exposes_configuration_and_masked_value():
    fake = FakeKeyring()
    validated = credential_settings._test_keyring(fake)
    credential_settings.set_credential("wind_mcp", "do-not-print-this", keyring_module=validated)

    statuses = credential_settings.list_credential_status(keyring_module=validated)

    assert statuses[0] == {"provider": "wind_mcp", "configured": True, "masked": "****"}
    assert all(set(item) == {"provider", "configured", "masked"} for item in statuses)
    assert all("do-not-print-this" not in str(item) for item in statuses)


def test_delete_is_idempotent_and_rejects_empty_values(monkeypatch):
    monkeypatch.delenv("WIND_MCP_AUTH", raising=False)
    monkeypatch.delenv("WIND_MCP_TOKEN", raising=False)
    fake = FakeKeyring()
    validated = credential_settings._test_keyring(fake)

    credential_settings.delete_credential("wind_mcp", keyring_module=validated)
    credential_settings.set_credential("wind_mcp", "secret", keyring_module=validated)
    credential_settings.delete_credential("wind_mcp", keyring_module=validated)
    credential_settings.delete_credential("wind_mcp", keyring_module=validated)

    assert credential_settings.get_credential("wind_mcp", keyring_module=validated) is None
    with pytest.raises(ValueError, match="Credential value cannot be empty"):
        credential_settings.set_credential("wind_mcp", "  ", keyring_module=fake)


def test_wind_credential_normalization_stays_in_wind_adapter(monkeypatch):
    monkeypatch.delenv("WIND_MCP_AUTH", raising=False)
    monkeypatch.delenv("WIND_MCP_TOKEN", raising=False)
    fake = FakeKeyring()
    validated = credential_settings._test_keyring(fake)
    credential_settings.set_credential("wind_mcp", "raw-wind-key", keyring_module=validated)
    monkeypatch.setattr(credential_settings, "_keyring", lambda: validated)

    assert credential_settings.get_credential("wind_mcp") == "raw-wind-key"


def test_plaintext_backend_is_rejected(monkeypatch):
    class PlaintextBackend:
        pass

    class PlaintextKeyring:
        def get_keyring(self):
            return PlaintextBackend()

    monkeypatch.setattr(credential_settings, "_import_keyring", lambda: PlaintextKeyring())

    with pytest.raises(RuntimeError, match="Windows Credential Vault backend"):
        credential_settings.set_credential("wind_mcp", "secret")


def test_raw_injected_keyring_cannot_bypass_backend_validation():
    with pytest.raises(RuntimeError, match="Unvalidated keyring injection"):
        credential_settings.set_credential("wind_mcp", "secret", keyring_module=FakeKeyring())
    with pytest.raises(RuntimeError, match="Unvalidated keyring adapter"):
        credential_settings._adapter_keyring(FakeKeyring())


def test_credential_status_type_contains_no_secret_field():
    assert set(credential_settings.CredentialStatus.__annotations__) == {
        "provider",
        "configured",
        "masked",
    }


def test_test_credential_does_not_return_secret():
    fake = FakeKeyring()
    validated = credential_settings._test_keyring(fake)
    credential_settings.set_credential("etfirst", "etfirst-secret", keyring_module=validated)

    result = credential_settings.test_credential("etfirst", keyring_module=validated)

    assert result == {"provider": "etfirst", "configured": True, "ok": True}
    assert "etfirst-secret" not in str(result)


def test_wind_environment_override_works_when_keyring_is_unavailable(monkeypatch):
    def unavailable():
        raise RuntimeError("keyring unavailable")

    monkeypatch.setattr(wind_credentials, "_keyring", unavailable)

    assert wind_credentials.get_authorization({"WIND_MCP_AUTH": "env-key"}) == "Bearer env-key"
    assert wind_credentials.get_authorization({"WIND_MCP_TOKEN": "token-key"}) == "Bearer token-key"


def test_wind_environment_override_has_priority_over_keyring(monkeypatch):
    fake = FakeKeyring()
    fake.set_password(credential_settings.SERVICE, "WIND_MCP_AUTH", "vault-key")
    validated = credential_settings._test_keyring(fake)
    monkeypatch.setattr(wind_credentials, "_keyring", lambda: validated)

    assert wind_credentials.get_authorization({"WIND_MCP_AUTH": "env-key"}) == "Bearer env-key"
