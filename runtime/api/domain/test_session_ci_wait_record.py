"""Gate-side CI wait record and resolve helpers stay advisory."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain.session_ci_wait_record import resolve_received_wait


class _Ok:
    success = True
    error = None


def test_binding_conclusions_dispatch_resolve() -> None:
    seen = []

    def dispatch(**kwargs):
        seen.append(kwargs)
        return _Ok()

    assert (
        resolve_received_wait(
            run_id="42",
            conclusion="success",
            dispatch=dispatch,
            session_id="s1",
        )
        == ""
    )
    assert seen[0]["function_id"] == "session_ci_wait.resolve"
    assert seen[0]["payload"] == {"run_id": "42", "conclusion": "success"}

    seen.clear()
    assert (
        resolve_received_wait(
            run_id="42",
            conclusion="failure",
            dispatch=dispatch,
            session_id="s1",
        )
        == ""
    )
    assert seen[0]["payload"]["conclusion"] == "failure"


def test_non_binding_conclusions_leave_the_wait_pending() -> None:
    def refuse(**_kwargs):  # pragma: no cover - the assertion is unused
        raise AssertionError("timeout must not consume the wait")

    for conclusion in ("timed_out", "cancelled", "error", "startup_failure"):
        assert (
            resolve_received_wait(
                run_id="42",
                conclusion=conclusion,
                dispatch=refuse,
                session_id="s1",
            )
            == ""
        )


def test_no_session_is_a_silent_noop() -> None:
    def refuse(**_kwargs):  # pragma: no cover - the assertion is unused
        raise AssertionError("no session means nobody to resolve")

    assert (
        resolve_received_wait(
            run_id="42",
            conclusion="success",
            dispatch=refuse,
            session_id="",
        )
        == ""
    )


def test_a_refused_resolve_warns_without_raising() -> None:
    def boom(**_kwargs):
        raise RuntimeError("control plane refused")

    warning = resolve_received_wait(
        run_id="42",
        conclusion="success",
        dispatch=boom,
        session_id="s1",
    )

    assert warning.startswith("ci wait not resolved:")
    assert "control plane refused" in warning


def test_an_unsuccessful_response_warns() -> None:
    response = SimpleNamespace(
        success=False,
        error=SimpleNamespace(message="session required"),
    )

    warning = resolve_received_wait(
        run_id="42",
        conclusion="success",
        dispatch=lambda **_k: response,
        session_id="s1",
    )

    assert warning == "ci wait not resolved: session required"
