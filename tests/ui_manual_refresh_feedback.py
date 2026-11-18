"""Check manual update feedback against a lagging-index result on an isolated UI."""

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from bench_frontend_round2 import CHROME, ROOT, copy_data, wait_server


def main():
    with tempfile.TemporaryDirectory(prefix="etf-refresh-feedback-") as temporary:
        data = Path(temporary)
        copy_data(data)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env={**os.environ, "ETF_DATA_DIR": str(data), "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            wait_server(base, process)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(CHROME), headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                job_id = "a" * 32
                def mocked_update(route):
                    url = route.request.url
                    if url.endswith("/api/jobs/update"):
                        body = {"job_id": job_id, "state": "QUEUED", "created": True}
                        route.fulfill(status=202, content_type="application/json", body=json.dumps(body))
                    elif url.endswith(f"/api/jobs/{job_id}/details"):
                        body = {"datasets": [
                            {"dataset_id": "etf_prices", "latest_date": "20261118"},
                            {"dataset_id": "index_prices", "latest_date": "20261117", "reason_code": "CNI_ROUTE_PENDING"},
                            {"dataset_id": "index:480080", "latest_date": "20261117", "reason_code": "CNI_ROUTE_PENDING"}]}
                        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
                    else:
                        body = {"job_id": job_id, "state": "PARTIAL", "stage": "PUBLISHED_WITH_PARTIAL_FAILURE",
                                "snapshot_id": "20261118T202021-92d1008a", "publication_status": "PUBLISHED"}
                        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
                page.route("**/api/jobs/**", mocked_update)
                page.goto(base + "/web/index.html?strategy=prism", wait_until="domcontentloaded")
                page.locator("#prism-observation strong").first.wait_for()
                page.locator("#refresh-data").click()
                page.wait_for_function("document.querySelector('#refresh-data').disabled === false")
                message = page.locator("#message").inner_text()
                state = page.locator("#message").get_attribute("data-state")
                assert "2026-11-18" in message and "2026-11-17" in message, message
                assert "成长100R" in message, message
                assert state == "warning", (state, message)
                assert not errors, errors
                print(json.dumps({"message": message, "state": state, "errors": errors}, ensure_ascii=False))
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
