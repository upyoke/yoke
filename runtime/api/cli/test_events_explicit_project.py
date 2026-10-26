"""Event reads scope only on an explicit project, regardless of checkout."""

from unittest.mock import patch
import pytest
from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_with_dispatch,
    _stub_dispatch_ok,
)


@pytest.mark.parametrize("verb", ["query", "count", "anomalies", "tail"])
@pytest.mark.parametrize("project", [None, "other"])
def test_read_ignores_ambient_checkout_and_preserves_explicit_project(verb, project):
    args = ["events", verb]
    if project:
        args += ["--project", project]

    def dispatch(req):
        return _stub_dispatch_ok(req).model_copy(
            update={"result": {"project": project}}
        )

    with patch(
        "yoke_cli.commands._helpers.client_project_context", return_value="yoke"
    ):
        assert _run_with_dispatch(dispatch, *args) == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.payload.get("project") == project
    assert req.target.project_id == project


def test_emit_still_uses_its_checkout_project():
    with patch(
        "yoke_cli.commands.adapters.events.client_project_context", return_value="yoke"
    ):
        assert (
            _run_with_dispatch(
                _stub_dispatch_ok,
                "events",
                "emit",
                "--name",
                "Probe",
                "--kind",
                "system",
                "--type",
                "test",
                "--source-type",
                "system",
            )
            == 0
        )
    assert _CAPTURED_REQUESTS[-1].payload["project"] == "yoke"
