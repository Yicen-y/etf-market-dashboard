"""Read and manage the local Wind MCP credential without storing it in the repo."""

from __future__ import annotations

import argparse
import getpass
import os
import sys

SERVICE = "etf-market-dashboard"
ACCOUNT = "WIND_MCP_AUTH"


def _keyring():
    import keyring
    backend = keyring.get_keyring()
    if "Windows" not in type(backend).__module__:
        raise RuntimeError("Windows Credential Vault backend is unavailable; refusing to store a plaintext credential")
    return keyring


def get_authorization(environ=None) -> str | None:
    env = os.environ if environ is None else environ
    value = env.get("WIND_MCP_AUTH") or env.get("WIND_MCP_TOKEN")
    if value:
        return _normalize(value)
    try:
        value = _keyring().get_password(SERVICE, ACCOUNT)
    except Exception:
        return None
    return _normalize(value) if value else None


def _normalize(value: str) -> str:
    value = value.strip()
    return value if value.lower().startswith(("bearer ", "basic ")) else f"Bearer {value}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Configure local Wind MCP credentials in Windows Credential Vault")
    parser.add_argument("action", choices=("set", "status", "delete", "check"))
    args = parser.parse_args(argv)
    try:
        keyring = _keyring()
        if args.action == "set":
            value = getpass.getpass("粘贴 Alice Market API Key / Authorization 值（输入不回显）: ").strip()
            if not value:
                print("未输入凭证；未做更改。")
                return 2
            keyring.set_password(SERVICE, ACCOUNT, value)
            print("Wind MCP 凭证已保存到 Windows 凭证库。")
        elif args.action == "delete":
            try:
                keyring.delete_password(SERVICE, ACCOUNT)
            except keyring.errors.PasswordDeleteError:
                pass
            print("Wind MCP 凭证已从 Windows 凭证库删除。")
        else:
            auth = get_authorization()
            if not auth:
                print("Wind MCP 凭证未配置。")
                return 2
            if args.action == "status":
                print("Wind MCP 凭证已配置（凭证值已隐藏）。")
                return 0
            from scripts.wind_config import DEFAULT_WIND_MCP_URL
            from scripts.wind_mcp_client import WindMcpClient
            with WindMcpClient(os.environ.get("WIND_MCP_URL", DEFAULT_WIND_MCP_URL), auth, timeout=60) as client:
                client.initialize()
                tools = client.list_tools()
            print(f"Wind MCP 连接成功；发现 {len(tools)} 个工具。")
        return 0
    except Exception as exc:
        print(f"Wind 凭证操作失败：{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
