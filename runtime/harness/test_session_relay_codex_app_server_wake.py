"""Codex app-server wake mechanics: status transitions and turn ownership.

Split from ``test_session_relay_codex.py`` (350-line authored cap). Shares
the ``context`` fixture from that module rather than duplicating it.
"""

from __future__ import annotations

from runtime.harness.session_relay_codex_app_server_wake_test_support import (
    FakeAppClient as FakeAppClient,
)


from pathlib import Path

import pytest

from yoke_harness import session_relay_codex as adapter_module
from yoke_harness import session_relay_codex_app_server as app_module
from yoke_harness.session_relay_codex import CodexNativeOutcome

from runtime.harness.session_relay_codex_test_support import (
    INSTRUCTION,
    SECRET,
    context,
)


@pytest.mark.parametrize(
    "wake_mode,status,mutation",
    [
        ("waiting", "active", "turn/steer"),
        ("idle_timeout", "idle", "turn/start"),
        ("waiting", "notLoaded", "turn/start"),
    ],
)
def test_app_server_uses_exact_status_and_id_with_fake_transport(
    monkeypatch,
    tmp_path: Path,
    wake_mode: str,
    status: str,
    mutation: str,
) -> None:
    client = FakeAppClient(status)
    monkeypatch.setattr(
        app_module.CodexAppServerTransport, "_client", lambda *_: client
    )
    request = adapter_module._request(
        context(
            tmp_path,
            surface="codex-desktop",
            job_kind="wake",
            target_liveness="active",
            wake_mode=wake_mode,
        )
    )[0]

    outcome = app_module.CodexAppServerTransport(worker=True).wake(request)

    assert outcome.state == "accepted"
    assert outcome.identity_correlated is True
    assert mutation in [method for method, _params in client.calls]
    mutation_params = next(
        params for method, params in client.calls if method == mutation
    )
    # Read the delivered text itself. `repr` of the params dict escapes
    # quotes inside the instruction, so a substring check against it fails
    # the moment the mandate text carries both quote characters — a
    # rendering artifact, not a delivery defect. The absence check stays on
    # `repr`, because it must cover the whole payload and not one field.
    assert INSTRUCTION in _delivered_text(mutation_params)
    assert SECRET not in repr(mutation_params)


def _delivered_text(params: dict) -> str:
    return "".join(
        part.get("text", "")
        for part in params.get("input", [])
        if isinstance(part, dict)
    )


def test_app_server_create_requires_vendor_thread_session_equality(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = FakeAppClient("idle", exact_identity=False)
    monkeypatch.setattr(
        app_module.CodexAppServerTransport, "_client", lambda *_: client
    )
    request = adapter_module._request(context(tmp_path, surface="codex-desktop"))[0]

    outcome = app_module.CodexAppServerTransport(worker=True).create(request)

    assert outcome.state == "outcome_unknown"
    assert "turn/start" not in [method for method, _params in client.calls]
    assert client.closed is True


def test_app_server_delegates_real_turn_ownership_out_of_serve_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = adapter_module._request(context(tmp_path, surface="codex-desktop"))[0]
    calls = []
    expected = CodexNativeOutcome("accepted", "native-1", True)
    monkeypatch.setattr(
        app_module.CodexAppServerTransport,
        "_detached",
        staticmethod(lambda value: calls.append(value) or expected),
    )

    outcome = app_module.CodexAppServerTransport().create(request)

    assert outcome == expected
    assert calls == [request]


def test_create_names_worker_before_starting_turn(monkeypatch, tmp_path):
    client = FakeAppClient("idle")
    monkeypatch.setattr(
        app_module.CodexAppServerTransport, "_client", lambda *_: client
    )
    worker = context(tmp_path)
    worker.session_name = "APP-12: Assigned work"
    request = adapter_module._request(worker)[0]
    outcome = app_module.CodexAppServerTransport(worker=True).create(request)
    assert outcome.state == "accepted"
    assert [method for method, _ in client.calls] == [
        "thread/start",
        "thread/name/set",
        "turn/start",
    ]
    assert client.calls[1][1] == {"threadId": "native-1", "name": worker.session_name}
