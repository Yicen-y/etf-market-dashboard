from pathlib import Path
import re


WEB = Path("web")


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_settings_page_uses_shared_shell_and_navigation():
    html = read("settings.html")
    assert 'lang="zh-CN"' in html
    assert 'href="theme.css' in html
    assert 'href="ui-components.css' in html
    assert 'href="settings.css' in html
    assert 'src="navigation.js' in html
    assert 'data-dashboard-navigation' in html
    assert 'data-active-section="settings"' in html


def test_settings_page_has_one_card_per_supported_provider():
    html = read("settings.html")
    for provider, label in (
        ("wind_mcp", "Wind MCP"),
        ("htbr_etf", "华泰柏瑞 ETF"),
        ("etfirst", "南方 ETFirst"),
    ):
        assert f'data-provider="{provider}"' in html
        assert label in html
    assert html.count('class="credential-card"') == 3


def test_settings_page_has_secret_controls_and_accessible_statuses():
    html = read("settings.html")
    assert html.count('type="password"') == 3
    assert 'autocomplete="new-password"' in html
    assert 'aria-label="显示或隐藏凭证"' in html
    assert 'aria-live="polite"' in html
    assert 'data-status' in html
    assert '保存凭证' in html
    assert '删除凭证' in html
    assert '测试连接' in html


def test_settings_script_uses_all_backend_operations_without_persisting_secrets():
    script = read("settings.js")
    assert "/api/settings/credentials" in script
    assert 'method: "PUT"' in script
    assert 'method: "DELETE"' in script
    assert 'method: "POST"' in script
    assert "/test" in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "URLSearchParams" not in script
    assert "window.location" not in script
    assert "location.search" not in script
    assert "credentialValue" not in script


def test_settings_script_prevents_duplicate_requests_and_redacts_messages():
    script = read("settings.js")
    assert "busy" in script
    assert "finally" in script
    assert "message" in script
    assert "凭证已保存" in script
    assert "凭证已删除" in script
    assert "连接测试" in script
    assert "操作未完成，请检查本地服务状态" in script
    assert "payload.detail" not in script


def test_settings_navigation_entry_and_active_state_exist():
    script = read("navigation.js")
    assert 'activeSection === "settings"' in script
    assert 'href="./settings.html"' in script
    assert "设置" in script
    assert 'current(activeSection === "settings")' in script
