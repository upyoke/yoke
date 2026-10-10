"""Signed job-event ordering across one-job runner rearm cycles."""

from datetime import timedelta
import shutil

import pytest

from yoke_contracts.timestamps import format_instant, utc_now
from runtime.api.domain.test_webapp_runner_lifecycle import (
    INSTANCE_ID,
    RUNNER_NAME,
    _parameters,
    _driver,
)
from runtime.api.domain.test_webapp_runner_github_broker import (
    _run_driver,
    _write_node_fixture,
)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_signed_in_progress_event_prevents_transient_offline_recycle(tmp_path):
    _write_node_fixture(tmp_path)
    parameters = _parameters(
        online_instance_id=INSTANCE_ID,
        progress_event={
            "action": "in_progress",
            "runner_name": RUNNER_NAME,
            "job_id": "789",
            "at": format_instant(utc_now()),
        },
    )
    payload = _run_driver(
        tmp_path,
        _driver("", parameters, [])
        + """
        const result = await handler({ action: "reap" });
        console.log(JSON.stringify({
          result, terminated: globalThis.__terminated,
        }));
    """,
    )

    assert payload["result"] == {
        "action": "kept",
        "reason": "job_event_in_progress",
    }
    assert payload["terminated"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
@pytest.mark.parametrize(
    "marker_age_seconds",
    [30, 600],
    ids=["startup-grace", "steady-state"],
)
def test_completion_opens_rearm_window_despite_delayed_in_progress_delivery(
    tmp_path,
    marker_age_seconds,
):
    _write_node_fixture(tmp_path)
    now = utc_now()
    parameters = _parameters(
        online_instance_id=INSTANCE_ID,
        marker_age_seconds=marker_age_seconds,
        progress_event={
            "action": "in_progress",
            "runner_name": RUNNER_NAME,
            "job_id": "789",
            "at": format_instant(now),
        },
        completion_event={
            "action": "completed",
            "runner_name": RUNNER_NAME,
            "job_id": "789",
            "at": format_instant(now - timedelta(seconds=5)),
        },
    )
    payload = _run_driver(
        tmp_path,
        _driver("", parameters, [])
        + """
        const result = await handler({ action: "reap" });
        console.log(JSON.stringify({
          result, terminated: globalThis.__terminated,
        }));
    """,
    )

    assert payload["result"] == {
        "action": "kept",
        "reason": "runner_rearm_window",
    }
    assert payload["terminated"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_previous_completion_does_not_override_newer_job_progress(tmp_path):
    _write_node_fixture(tmp_path)
    now = utc_now()
    parameters = _parameters(
        online_instance_id=INSTANCE_ID,
        marker_age_seconds=600,
        progress_event={
            "action": "in_progress",
            "runner_name": RUNNER_NAME,
            "job_id": "new-job",
            "at": format_instant(now),
        },
        completion_event={
            "action": "completed",
            "runner_name": RUNNER_NAME,
            "job_id": "previous-job",
            "at": format_instant(now - timedelta(seconds=30)),
        },
    )
    payload = _run_driver(
        tmp_path,
        _driver("", parameters, [])
        + """
        const result = await handler({ action: "reap" });
        console.log(JSON.stringify({
          result, terminated: globalThis.__terminated,
        }));
    """,
    )

    assert payload["result"] == {
        "action": "kept",
        "reason": "job_event_in_progress",
    }
    assert payload["terminated"] is None
