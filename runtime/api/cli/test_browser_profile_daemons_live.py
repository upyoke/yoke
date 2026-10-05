"""Real Chromium captures survive other profiles' starts, stops and idle exit.

Uses disposable profiles and candidate daemon sources, with the host's installed
Playwright dependencies. Absent browser dependencies make this a named skip.
"""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import shutil
import threading
import time

import pytest

from yoke_contracts.browser_qa_contract import DEFAULT_BROWSER_VIEWPORT
from yoke_contracts.playwright_cache import (
    YOKE_BROWSER_CACHE_PROJECT,
    resolve_playwright_cache,
)
from yoke_core.domain import browser_client as core_client
from yoke_harness import browser_client, browser_runtime, browser_runtime_home
from yoke_harness.browser_daemon_profile import profile_scope


class ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        name = self.path.strip("/") or "empty"
        body = f"<html><body>{name}; cookie={self.headers.get('Cookie', 'none')}</body></html>".encode()
        self.send_response(200)
        if name in {"alpha", "beta"}:
            self.send_header("Set-Cookie", f"profile={name}; Path=/")
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def daemon_runtime(tmp_path, monkeypatch):
    installed = Path.home() / ".yoke" / browser_runtime_home.RUNTIME_DIR_NAME
    if (
        not shutil.which("node")
        or not (installed / "node_modules" / "playwright").is_dir()
    ):
        if os.environ.get("DEPLOYMENT_RUN_ID"):
            pytest.fail(
                "install the host Playwright runtime before deployed capture QA"
            )
        pytest.skip("machine has no materialized Playwright browser runtime")
    runtime = tmp_path / "runtime"
    shutil.copytree(Path(browser_runtime.__file__).parent / "src", runtime / "src")
    (runtime / "node_modules").symlink_to(
        installed / "node_modules", target_is_directory=True
    )
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: runtime)
    monkeypatch.setattr(core_client, "_browser_dir", lambda: runtime)
    env = dict(os.environ)
    cache = resolve_playwright_cache(YOKE_BROWSER_CACHE_PROJECT, None)
    host_cache = Path.home() / ".yoke" / "playwright-cache" / YOKE_BROWSER_CACHE_PROJECT
    if not cache and host_cache.is_dir():
        cache = host_cache
    if cache:
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(cache)
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(cache))
    monkeypatch.setattr(
        "yoke_harness.browser_client.ensure_browser_runtime",
        lambda *args, **kwargs: env,
    )
    return runtime


@pytest.mark.parametrize("starter", [browser_client, core_client])
def test_two_profiles_capture_concurrently_without_page_or_cookie_loss(
    daemon_runtime, tmp_path, starter
):
    profiles = [str(tmp_path / name) for name in ("alpha", "beta")]
    for profile in profiles:
        Path(profile).mkdir()
    with ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            first = starter.daemon_start(profile_dir=profiles[0], idle_timeout=30000)
            with profile_scope(profiles[0]):
                alpha = core_client.open_owned_page(DEFAULT_BROWSER_VIEWPORT)
                core_client.execute_step(
                    {"action": "navigate", "route": "/alpha"}, base_url, page_id=alpha
                )
            second = browser_client.daemon_start(
                profile_dir=profiles[1], idle_timeout=30000
            )
            assert first["pid"] != second["pid"]
            assert first["endpoint"] != second["endpoint"]
            assert (
                browser_client.daemon_start(profile_dir=profiles[0])["status"]
                == "already_running"
            )
            with profile_scope(profiles[0]):
                sibling = core_client.open_owned_page({"width": 800, "height": 600})
                assert sibling != alpha
                core_client.execute_step(
                    {"action": "navigate", "route": "/sibling"},
                    base_url,
                    page_id=sibling,
                )
            with profile_scope(profiles[1]):
                beta = core_client.open_owned_page(DEFAULT_BROWSER_VIEWPORT)
                core_client.execute_step(
                    {"action": "navigate", "route": "/beta"}, base_url, page_id=beta
                )

            def capture(profile, page, expected):
                with profile_scope(profile):
                    response = core_client.execute_step(
                        {
                            "action": "assert",
                            "target": "body",
                            "check": "text_contains",
                            "expected": expected,
                        },
                        base_url,
                        page_id=page,
                    )
                    assert response["success"], response
                    shot = core_client.execute_step(
                        {"action": "screenshot", "label": expected},
                        base_url,
                        str(tmp_path / expected),
                        page_id=page,
                    )
                    assert shot["success"], shot
                    return shot

            with ThreadPoolExecutor(max_workers=3) as workers:
                list(
                    workers.map(
                        lambda args: capture(*args),
                        [
                            (profiles[0], alpha, "alpha"),
                            (profiles[0], sibling, "sibling"),
                            (profiles[1], beta, "beta"),
                        ],
                    )
                )
            with profile_scope(profiles[1]):
                core_client.execute_step(
                    {"action": "navigate", "route": "/check"}, base_url, page_id=beta
                )
                capture(profiles[1], beta, "profile=beta")
            with profile_scope(profiles[0]):
                core_client.execute_step(
                    {"action": "navigate", "route": "/check"}, base_url, page_id=alpha
                )
                capture(profiles[0], alpha, "profile=alpha")
            browser_client.daemon_stop(profile_dir=profiles[1])
            assert (
                browser_client.daemon_status(profile_dir=profiles[0])["status"]
                == "running"
            )
            capture(profiles[0], sibling, "sibling")
            # Leave time for the 250ms readiness poll before testing idle exit.
            # The second profile's shutdown still removes only its own state.
            browser_client.daemon_start(profile_dir=profiles[1], idle_timeout=2000)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if (
                    browser_client.DaemonState.load(
                        browser_client._state_file_path(profiles[1])
                    )
                    is None
                ):
                    break
                time.sleep(0.1)
            assert (
                browser_client.daemon_status(profile_dir=profiles[1])["status"]
                != "running"
            )
            capture(profiles[0], sibling, "sibling")
        finally:
            for profile in profiles:
                try:
                    browser_client.daemon_stop(profile_dir=profile)
                except RuntimeError:
                    pass
            server.shutdown()
