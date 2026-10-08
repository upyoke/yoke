"""Real Chromium media evidence through the registered Browser case runner.

The browser-runtime CI job provisions Chromium and opts into this substrate
test. Ordinary Python shards do not provision a browser. Persistence uses the
existing disposable DB recorder; opening, steps and screenshots use real pages.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

import pytest

from yoke_core.domain import browser_client
from yoke_contracts.playwright_cache import (
    YOKE_BROWSER_CACHE_PROJECT,
    resolve_playwright_cache,
)
from yoke_core.domain.qa_case_execution import execute_case_context
from runtime.api.domain.browser_qa_test_helpers import (
    _patch_external_deps,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import init_test_db, connect_test_db

pytestmark = pytest.mark.skipif(
    os.environ.get("YOKE_BROWSER_INTEGRATION") != "1",
    reason="real Chromium integration runs in the provisioning browser-runtime CI job",
)
RUNTIME = (
    Path(__file__).resolve().parents[3]
    / "packages/yoke-harness/src/yoke_harness/browser_runtime"
)


@pytest.fixture
def daemon(monkeypatch, tmp_path):
    environment = os.environ.copy()
    environment.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH",
        resolve_playwright_cache(YOKE_BROWSER_CACHE_PROJECT, None),
    )
    with (tmp_path / "daemon.log").open("w+") as log:
        process = subprocess.Popen(
            ["node", str(RUNTIME / "tests/color-scheme.test.js"), "--serve"],
            cwd=RUNTIME,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
            env=environment,
        )
        try:
            line = process.stdout.readline()
            if not line:
                log.seek(0)
                pytest.fail(f"color scheme fixture did not start: {log.read()}")
            url = json.loads(line)["url"]

            def request(endpoint, body=None, **_kwargs):
                message = urllib.request.Request(
                    url + endpoint,
                    data=json.dumps(body or {}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(message, timeout=20) as response:
                        return json.load(response)
                except urllib.error.HTTPError as exc:
                    raise RuntimeError(json.load(exc)["error"]) from exc

            monkeypatch.setattr(browser_client, "daemon_request", request)
            monkeypatch.setattr(browser_client, "daemon_running", lambda: True)
            yield url
        finally:
            process.terminate()
            process.wait(timeout=20)


def test_registered_cases_capture_light_and_dark_without_inheritance(daemon, tmp_path):
    screenshots = []
    with init_test_db(tmp_path) as db_path:
        item = 876
        _seed_item(db_path, item)
        for scheme in ("light", "dark", None):
            config = {
                "steps": [
                    {"action": "navigate", "route": "/fixture"},
                    {
                        "action": "assert",
                        "target": "#mode",
                        "check": "text_equals",
                        "expected": scheme or "light",
                    },
                    {"action": "click", "target": "#reload"},
                    {
                        "action": "assert",
                        "target": "#mode",
                        "check": "text_equals",
                        "expected": scheme or "light",
                    },
                    {"action": "click", "target": "#next"},
                    {
                        "action": "assert",
                        "target": "#mode",
                        "check": "text_equals",
                        "expected": scheme or "light",
                    },
                    {"action": "screenshot", "capture": True},
                ],
                "viewport": {"width": 640, "height": 480},
            }
            if scheme is not None:
                config["color_scheme"] = scheme
            req = _seed_requirement(db_path, item, "browser-check", config)
            with ExitStack() as stack:
                for patch in _patch_external_deps(db_path):
                    if patch.attribute not in ("open_owned_page", "close_owned_page"):
                        stack.enter_context(patch)
                result = execute_case_context(
                    {
                        "public_ref": item,
                        "item_id": item,
                        "requirement_id": req,
                        "project": "testproj",
                        "project_id": 1,
                        "runner_id": "browser_substrate",
                        "method_config": config,
                    },
                    base_url=daemon,
                )
            assert result["verdict"] == "pass", result
            conn = connect_test_db(db_path)
            raw = json.loads(
                conn.execute(
                    "SELECT raw_result FROM qa_runs WHERE qa_requirement_id = %s ORDER BY id DESC",
                    (req,),
                ).fetchone()[0]
            )
            metadata = json.loads(
                conn.execute(
                    "SELECT metadata FROM qa_artifacts WHERE qa_run_id = %s",
                    (result["qa_run_id"],),
                ).fetchone()[0]
            )
            conn.close()
            assert raw["color_scheme"] == {
                "requested": scheme,
                "observed": scheme or "light",
            }
            assert metadata["color_scheme"] == raw["color_scheme"]
            assert metadata["viewport"] == config["viewport"]
            assert metadata["observed_url"] == daemon + "/next"
            image = Path(raw["artifacts"][0]).read_bytes()
            assert image.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10]))
            screenshots.append(image)
        assert screenshots[0] != screenshots[1]
        assert screenshots[0] == screenshots[2]
