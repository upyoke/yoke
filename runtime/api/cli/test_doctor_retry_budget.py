"""Doctor retries spend one deadline, retaining completed rows on failure."""

import io
from types import SimpleNamespace
import urllib.error

from yoke_cli.transport import https as relay
from yoke_cli.transport import response_deadline_read
from yoke_cli.commands.adapters import doctor_https_run as doctor
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from runtime.api.cli.https_relay_security_test_support import (
    CONNECTION,
    sensitive_request,
)


def test_gateway_retries_are_capped_and_do_not_renew_deadline(monkeypatch, capsys):
    now = [0.0]
    calls = []
    monkeypatch.setattr(relay, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(response_deadline_read, "monotonic", lambda: now[0])
    monkeypatch.setattr(relay, "record_outcome", lambda *a, **k: None)

    def open_request(request, *, deadline, timeout_s):
        calls.append((deadline, timeout_s, request.data))
        now[0] += 20
        raise urllib.error.HTTPError(
            CONNECTION.functions_url,
            503,
            "unavailable",
            {},
            io.BytesIO(b"gateway unavailable"),
        )

    monkeypatch.setattr(relay, "_open_function_relay", open_request)
    request = sensitive_request().model_copy(update={"function": "doctor.run.run"})
    response = relay.relay_https(
        request,
        CONNECTION,
        timeout_s=300,
        sleep=lambda delay: now.__setitem__(0, now[0] + delay),
    )
    assert not response.success
    assert response.request_id == request.request_id
    assert len(calls) == 2
    assert [call[0] for call in calls] == [60, 60]
    assert [call[1] for call in calls] == [60, 39]
    assert calls[0][2] == calls[1][2]
    assert now[0] < 60
    assert "attempt 1/2" in capsys.readouterr().err


def test_exhausted_chunk_is_not_reexecuted(monkeypatch):
    now = [0.0]
    calls = []
    monkeypatch.setattr(relay, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(response_deadline_read, "monotonic", lambda: now[0])
    monkeypatch.setattr(relay, "record_outcome", lambda *a, **k: None)

    def open_request(*a, **k):
        calls.append(k)
        now[0] = 60
        raise relay.ResponseOpenDeadlineError("expired")

    monkeypatch.setattr(relay, "_open_function_relay", open_request)
    request = sensitive_request().model_copy(update={"function": "doctor.run.run"})
    response = relay.relay_https(request, CONNECTION, timeout_s=300)
    assert len(calls) == 1
    assert "doctor_chunk_budget_exhausted" in response.error.message


def test_overall_deadline_retains_rows_cursor_and_error_identity(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(doctor, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(doctor, "RUN_BUDGET_S", 60)
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        now[0] = 60
        return FunctionCallResponse(
            success=True,
            function="doctor.run.run",
            version="v1",
            request_id="completed-request",
            result={
                "results": [{"hc": "HC-first", "severity": "PASS"}],
                "done": False,
                "cursor": "first",
                "pass_count": 1,
            },
        )

    monkeypatch.setattr(doctor, "call_dispatcher", dispatch)
    response = doctor.collect_chunked(
        payload={"full": True}, session_id=None, chunk_max_checks=1, timeout_s=300
    )
    assert len(calls) == 1
    assert not response.success
    assert response.result["results"] == [{"hc": "HC-first", "severity": "PASS"}]
    assert response.result["cursor"] == "first"
    assert response.result["completed_control_plane_batches"] == 1
    assert "doctor_run_budget_exhausted" in response.error.message


def test_failed_chunk_retains_original_error_and_request_id(monkeypatch):
    error = FunctionError(code="https_transport_failed", message="gateway unavailable")
    responses = iter(
        [
            FunctionCallResponse(
                success=True,
                function="doctor.run.run",
                version="v1",
                request_id="first",
                result={
                    "results": [{"hc": "HC-first"}],
                    "done": False,
                    "cursor": "first",
                    "pass_count": 1,
                },
            ),
            FunctionCallResponse(
                success=False,
                function="doctor.run.run",
                version="v1",
                request_id="failed-request",
                error=error,
            ),
        ]
    )
    monkeypatch.setattr(doctor, "call_dispatcher", lambda **k: next(responses))
    response = doctor.collect_chunked(
        payload={"full": True}, session_id=None, chunk_max_checks=1, timeout_s=300
    )
    assert response.error == error
    assert response.request_id == "failed-request"
    assert response.result["pass_count"] == 1
