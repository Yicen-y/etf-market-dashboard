"""Local credential storage for the ETF dashboard.

Credentials are stored in the Windows Credential Manager through ``keyring``.
The service deliberately exposes status only as configured/masked metadata.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

SERVICE = "etf-market-dashboard"


class CredentialProvider(str, Enum):
    WIND_MCP = "wind_mcp"
    HTBR_ETF = "htbr_etf"
    ETFIRST = "etfirst"


@dataclass(frozen=True)
class CredentialSpec:
    account: str
    environment_names: tuple[str, ...]


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
    return keyring


def _provider(provider: CredentialProvider | str) -> CredentialProvider:
    try:
        return provider if isinstance(provider, CredentialProvider) else CredentialProvider(provider)
    except ValueError as exc:
        raise ValueError(f"Unsupported credential provider: {provider}") from exc


def _spec(provider: CredentialProvider | str) -> tuple[CredentialProvider, CredentialSpec]:
    normalized = _provider(provider)
    return normalized, _SPECS[normalized]


def _backend(keyring_module=None):
    # Explicit injection is intentionally supported for deterministic tests and
    # adapters; production callers use the validated Windows backend above.
    return keyring_module if keyring_module is not None else _keyring()


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
) -> list[dict[str, Any]]:
    return [
        {
            "provider": provider.value,
            "configured": bool(get_credential(provider, environ, keyring_module=keyring_module)),
            "masked": _mask(get_credential(provider, environ, keyring_module=keyring_module)),
        }
        for provider in CredentialProvider
    ]


def test_credential(
    provider: CredentialProvider | str,
    environ: Mapping[str, str] | None = None,
    *,
    keyring_module=None,
) -> dict[str, Any]:
    normalized = _provider(provider)
    configured = bool(get_credential(normalized, environ, keyring_module=keyring_module))
    return {"provider": normalized.value, "configured": configured, "ok": configured}
