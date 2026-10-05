"""Opt-in deployed browser capture proof for two configured project profiles."""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier

import pytest

from yoke_cli.config.browser_profile import authorized_profile_dir
from yoke_contracts.browser_qa_contract import DEFAULT_BROWSER_VIEWPORT
from yoke_core.domain import browser_client
from yoke_harness.browser_daemon_profile import project_scope
from yoke_harness.browser_qa_daemon import ensure_daemon_running


def test_named_projects_capture_at_once(tmp_path):
    projects = os.environ.get("YOKE_BROWSER_CAPTURE_PROJECTS", "").split(",")
    base_url = os.environ.get("BASE_URL", "")
    if len(projects) != 2 or not all(projects) or not base_url:
        if os.environ.get("DEPLOYMENT_RUN_ID"):
            pytest.fail("deployed capture QA requires two projects and BASE_URL")
        pytest.skip(
            "requires two YOKE_BROWSER_CAPTURE_PROJECTS and the deployed BASE_URL"
        )
    profiles = [authorized_profile_dir(project) for project in projects]
    assert all(profiles), (
        "authorize both named projects before the deployed capture proof"
    )
    assert profiles[0].resolve() != profiles[1].resolve()
    barrier = Barrier(2)

    def capture(project):
        error = ensure_daemon_running(project)
        assert error is None, error
        with project_scope(project):
            state = browser_client.DaemonState.load()
            page = browser_client.open_owned_page(DEFAULT_BROWSER_VIEWPORT)
            try:
                response = browser_client.execute_step(
                    {"action": "navigate", "route": "/"}, base_url, page_id=page
                )
                assert response["success"], response
                barrier.wait(timeout=60)
                result = browser_client.execute_step(
                    {"action": "screenshot", "capture": True, "label": project},
                    base_url,
                    str(tmp_path / project),
                    page_id=page,
                )
                assert result["success"], result
                artifacts = result["data"]["artifacts"]
                assert artifacts, result
                # The other profile's concurrent work did not replace this daemon.
                assert browser_client.DaemonState.load().pid == state.pid
                print(
                    f"{project}: capture completed on pid={state.pid} endpoint={state.endpoint}; artifacts={artifacts}"
                )
                return state.pid, state.endpoint
            finally:
                browser_client.close_owned_page(page)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(capture, projects))
    assert results[0][0] != results[1][0]
    assert results[0][1] != results[1][1]
