"""An evidence-read job success is not a session-liveness verdict."""

import io
from types import SimpleNamespace

from yoke_cli.commands.adapters.session_control_evidence import _write_evidence


def test_evidence_success_is_labelled_as_fetch_job_state():
    out = io.StringIO()
    _write_evidence(
        SimpleNamespace(
            result={"session_id": "worker", "state": "succeeded", "result_code": "read"}
        ),
        out,
        io.StringIO(),
    )
    assert "FETCH JOB STATE" in out.getvalue()
    assert "succeeded" in out.getvalue()
