"""Local credential storage for the ETF dashboard.

Credentials are stored in the Windows Credential Manager through ``keyring``.
The service deliberately exposes status only as configured/masked metadata.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, TypedDict

SERVICE = "etf-market-dashboard"


class CredentialProvider(str, Enum):
    WIND_MCP = "wind_mcp"
    HTBR_ETF = "htbr_etf"
    ETFIRST = "etfirst"


class CredentialStatus(TypedDict):
    """Non-secret status shape exposed to settings/API callers."""

    provider: str
    configured: bool
    masked: str


@dataclass(frozen=True)
class CredentialSpec:
    account: str
    environment_names: tuple[str, ...]


class ValidatedKeyring:
    """A keyring module whose backend has passed the Windows-only check."""

    def __init__(self, module):
        self.module = module

    def get_password(self, service, account):
        return self.module.get_password(service, account)

    def set_password(self, service, account, value):
        return self.module.set_password(service, account, value)

    def delete_password(self, service, account):
        return self.module.delete_password(service, account)

    @property
    def errors(self):
        return getattr(self.module, "errors", None)


_SPECS: dict[CredentialProvider, CredentialSpec] = {
    CredentialProvider.WIND_MCP: CredentialSpec("WIND_MCP_AUTH", ("WIND_MCP_AUTH", "WIND_MCP_TOKEN")),
    CredentialProvider.HTBR_ETF: CredentialSpec("HTBR_ETF_API_KEY", ("HTBR_ETF_API_KEY",)),
    CredentialProvider.ETFIRST: CredentialSpec("ETFIRST_API_KEY", ("ETFIRST_API_KEY",)),
}


def _import_keyring():
    import keyring

    return keyring


def _keyring():
    keyring = _import_keyring()
    backend = keyring.get_keyring()
    module_name = type(backend).__module__.lower()
    backend_name = type(backend).__name__.lower()
    if "windows" not in module_name and "wincred" not in backend_name:
        raise RuntimeError(
            "Windows Credential Vault backend is unavailable; refusing to store a plaintext credential"
        )
    return ValidatedKeyring(keyring)


def normalize_provider(provider: CredentialProvider | str) -> CredentialProvider:
    """Return the canonical provider enum, accepting documented aliases."""
    if provider == "htbr":
        provider = CredentialProvider.HTBR_ETF
    try:
        return provider if isinstance(provider, CredentialProvider) else CredentialProvider(provider)
    except ValueError as exc:
        raise ValueError(f"Unsupported credential provider: {provider}") from exc


def _provider(provider: CredentialProvider | str) -> CredentialProvider:
    return normalize_provider(provider)


def _spec(provider: CredentialProvider | str) -> tuple[CredentialProvider, CredentialSpec]:
    normalized = _provider(provider)
    return normalized, _SPECS[normalized]


def _test_keyring(keyring_module) -> ValidatedKeyring:
    """Wrap an in-memory fake for tests without widening the public seam."""
    return ValidatedKeyring(keyring_module)


def _adapter_keyring(keyring_module) -> ValidatedKeyring:
    """Adapt an already-validated CLI keyring to the service boundary."""
    if not isinstance(keyring_module, ValidatedKeyring):
        raise RuntimeError(
            "Unvalidated keyring adapter is refused; use the Windows Credential Vault backend"
        )
    return keyring_module


def _backend(keyring_module=None):
    if keyring_module is None:
        return _keyring()
    if not isinstance(keyring_module, ValidatedKeyring):
        raise RuntimeError(
            "Unvalidated keyring injection is refused; use the Windows Credential Vault backend"
        )
    return keyring_module


def _environment_value(spec: CredentialSpec, environ: Mapping[str, str] | None) -> str | None:
    env = os.environ if environ is None else environ
    for name in spec.environment_names:
        value = env.get(name)
        if value and value.strip():
            return value.strip()
    return None


def get_credential(
    provider: CredentialProvider | str,
    environ: Mapping[str, str] | None = None,
    *,
    keyring_module=None,
) -> str | None:
    _, spec = _spec(provider)
    override = _environment_value(spec, environ)
    if override:
        return override
    return _backend(keyring_module).get_password(SERVICE, spec.account)


def set_credential(
    provider: CredentialProvider | str,
    value: str,
    *,
    keyring_module=None,
) -> None:
    _, spec = _spec(provider)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Credential value cannot be empty")
    _backend(keyring_module).set_password(SERVICE, spec.account, value.strip())


def delete_credential(provider: CredentialProvider | str, *, keyring_module=None) -> None:
    _, spec = _spec(provider)
    backend = _backend(keyring_module)
    try:
        backend.delete_password(SERVICE, spec.account)
    except Exception as exc:
        errors = getattr(backend, "errors", None)
        delete_error = getattr(errors, "PasswordDeleteError", None)
        if delete_error is None or not isinstance(exc, delete_error):
            raise


def _mask(value: str | None) -> str:
    return "****" if value else ""


def list_credential_status(
    environ: Mapping[str, str] | None = None,
    *,
    keyring_module=None,
) -> list[CredentialStatus]:
    statuses = []
    for provider in CredentialProvider:
        value = get_credential(provider, environ, keyring_module=keyring_module)
        statuses.append(
            {"provider": provider.value, "configured": bool(value), "masked": _mask(value)}
        )
    return statuses


def test_credential(
    provider: CredentialProvider | str,
    environ: Mapping[str, str] | None = None,
    *,
    keyring_module=None,
) -> dict[str, Any]:
    normalized = _provider(provider)
    value = get_credential(normalized, environ, keyring_module=keyring_module)
    configured = bool(value)
    if not configured:
        return {"provider": normalized.value, "configured": False, "ok": False,
                "remote_verified": False, "status": "not_configured", "message": "未配置凭证"}

    child_env = dict(os.environ if environ is None else environ)
    child_env[_SPECS[normalized].account] = value
    try:
        if normalized is CredentialProvider.ETFIRST:
            command = ["etfirst", "--json", "config", "--no-show"]
        elif normalized is CredentialProvider.HTBR_ETF:
            from pathlib import Path
            skill_root = Path.home() / ".codex" / "skills" / "htbr-etf-skill"
            python = child_env.get("HTBR_PYTHON") or os.sys.executable
            command = [python, str(skill_root / "config.py"), "status"]
        else:
            from scripts.wind_credentials import get_authorization
            from scripts.wind_config import DEFAULT_WIND_MCP_URL
            from scripts.wind_mcp_client import WindMcpClient
            authorization = get_authorization(child_env)
            with WindMcpClient(child_env.get("WIND_MCP_URL", DEFAULT_WIND_MCP_URL), authorization, timeout=15) as client:
                client.initialize()
                tools = client.list_tools()
            return {"provider": normalized.value, "configured": True, "ok": True,
                    "remote_verified": True, "status": "remote_verified",
                    "message": f"连接成功（发现 {len(tools)} 个工具）"}

        completed = subprocess.run(
            command, env=child_env, capture_output=True, text=True,
            timeout=15, check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("提供方返回失败")
        # ETFirst config and HTBR status are local checks only.  They do not
        # prove that the remote gateway accepts the credential.
        return {"provider": normalized.value, "configured": True, "ok": False,
                "remote_verified": False, "status": "not_verified",
                "message": "本地配置检查通过；未验证远程服务"}
    except Exception as exc:
        # Never expose command output or the configured value in the status API.
        return {"provider": normalized.value, "configured": True, "ok": False,
                "remote_verified": False, "status": "check_failed",
                "message": f"{type(exc).__name__}: {str(exc).replace(value, '[REDACTED]')}"}
