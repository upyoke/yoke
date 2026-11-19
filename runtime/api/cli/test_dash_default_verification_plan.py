"""A Dash filed without a verification choice takes the registered quick plan."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import dash_file, dash_verification_plan, items_create

QUICK_SLUG = "registered-command-quick"


@pytest.fixture(autouse=True)
def _spec_on_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO("Instruction"))


def _catalog(monkeypatch: pytest.MonkeyPatch, outcome) -> list[dict]:
    """Serve ``qa.plan.get`` from ``outcome``: a plan dict or an error code."""
    lookups: list[dict] = []

    def _call_dispatcher(**kwargs):
        lookups.append(kwargs)
        if isinstance(outcome, dict):
            return SimpleNamespace(success=True, result={"plan": outcome}, error=None)
        return SimpleNamespace(
            success=False,
            result=None,
            error=SimpleNamespace(code=outcome, message=f"{outcome} from server"),
        )

    monkeypatch.setattr(
        dash_verification_plan._helpers, "ensure_handlers_loaded", lambda: None
    )
    monkeypatch.setattr(dash_verification_plan, "call_dispatcher", _call_dispatcher)
    return lookups


def _filing(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(items_create, "dispatch_create", _dispatch)
    return captured


def _file_dash(*extra: str) -> int:
    return dash_file.dash_file(
        ["--title", "Title", "--stdin", "--project", "yoke", *extra]
    )


def test_unnamed_verification_selects_the_registered_quick_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lookups = _catalog(monkeypatch, {"id": 41, "slug": QUICK_SLUG, "retired_at": None})
    captured = _filing(monkeypatch)

    assert _file_dash("--json") == 0

    assert [call["payload"] for call in lookups] == [
        {"project": "yoke", "plan_id": QUICK_SLUG}
    ]
    assert captured["payload"]["workflow_posture"] == {
        "verification": {"kind": "plan", "plan_id": 41}
    }
    assert (
        f"verification plan: {QUICK_SLUG} (project default)"
        in capsys.readouterr().err
    )


@pytest.mark.parametrize(
    "outcome",
    ["not_found", {"id": 41, "slug": QUICK_SLUG, "retired_at": "2026-11-01T00:00:00Z"}],
    ids=["no-registered-command", "retired-by-no-tests-attestation"],
)
def test_no_active_quick_plan_files_an_empty_posture(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], outcome
) -> None:
    _catalog(monkeypatch, outcome)
    captured = _filing(monkeypatch)

    assert _file_dash() == 0

    assert captured["payload"]["workflow_posture"] == {}
    assert "project default" not in capsys.readouterr().err


def test_verification_method_none_skips_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups = _catalog(monkeypatch, {"id": 41, "slug": QUICK_SLUG, "retired_at": None})
    captured = _filing(monkeypatch)

    assert _file_dash("--verification-method", "none") == 0

    assert lookups == []
    assert captured["payload"]["workflow_posture"] == {}


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (("--verification-plan", "38"), {"kind": "plan", "plan_id": 38}),
        (
            ("--verification-method", "browser-inspection"),
            {"kind": "ad_hoc", "method_id": "browser-inspection"},
        ),
    ],
)
def test_an_explicit_verification_choice_wins(
    monkeypatch: pytest.MonkeyPatch, flags, expected
) -> None:
    lookups = _catalog(monkeypatch, {"id": 41, "slug": QUICK_SLUG, "retired_at": None})
    captured = _filing(monkeypatch)

    assert _file_dash(*flags) == 0

    assert lookups == []
    assert captured["payload"]["workflow_posture"]["verification"] == expected


def test_an_unreadable_catalog_refuses_with_both_recoveries(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _catalog(monkeypatch, "internal_error")
    captured = _filing(monkeypatch)

    assert _file_dash() == 2

    error = capsys.readouterr().err
    assert captured == {}
    assert QUICK_SLUG in error
    assert "internal_error from server" in error
    assert "--verification-plan ID_OR_SLUG" in error
    assert "--verification-method none" in error
