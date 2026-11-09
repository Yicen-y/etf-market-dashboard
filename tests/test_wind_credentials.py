from scripts import wind_credentials


class FakeKeyring:
    class errors:
        class PasswordDeleteError(Exception):
            pass

    def __init__(self):
        self.saved = None

    def get_password(self, service, account):
        return self.saved

    def set_password(self, service, account, value):
        self.saved = value


def test_credentials_prefer_environment_then_windows_vault(monkeypatch):
    fake = FakeKeyring()
    fake.saved = "vault-key"
    monkeypatch.setattr(wind_credentials, "_keyring", lambda: fake)
    assert wind_credentials.get_authorization({}) == "Bearer vault-key"
    assert wind_credentials.get_authorization({"WIND_MCP_AUTH": "Bearer env-key"}) == "Bearer env-key"
    assert wind_credentials.get_authorization({"WIND_MCP_TOKEN": "token-key"}) == "Bearer token-key"


def test_auth_header_value_is_not_modified():
    assert wind_credentials._normalize("AuthorizationRaw") == "Bearer AuthorizationRaw"
    assert wind_credentials._normalize("Bearer AuthorizationRaw") == "Bearer AuthorizationRaw"


def test_set_action_saves_secret_without_printing_it(monkeypatch, capsys):
    fake = FakeKeyring()
    monkeypatch.setattr(wind_credentials, "_keyring", lambda: fake)
    monkeypatch.setattr(wind_credentials.getpass, "getpass", lambda _prompt: "secret-value")
    assert wind_credentials.main(["set"]) == 0
    assert fake.saved == "secret-value"
    assert "secret-value" not in capsys.readouterr().out
