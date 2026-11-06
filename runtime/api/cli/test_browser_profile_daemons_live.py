"""Real Chromium captures survive other profiles' starts, stops and idle exit.

Uses disposable profiles and candidate daemon sources, with the host's installed
Playwright dependencies. Absent browser dependencies make this a named skip.
"""

from runtime.api.cli.browser_profile_daemons_live_test_support import (
    ProbeHandler as ProbeHandler,
    daemon_runtime as daemon_runtime,
)


from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import time

import pytest

from yoke_contracts.browser_qa_contract import DEFAULT_BROWSER_VIEWPORT
from yoke_core.domain import browser_client as core_client
from yoke_harness import browser_client
from yoke_contracts.browser_daemon_profile import profile_scope


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
