from pathlib import Path


def test_workflow_has_schedule_data_update_tests_and_pages_deploy():
    text = Path(".github/workflows/daily-update.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "cron:" in text
    assert "update_data" in text
    assert "python -m pytest -q" in text
    assert "actions/deploy-pages@v4" in text

