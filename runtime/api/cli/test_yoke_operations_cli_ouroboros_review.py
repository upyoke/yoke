"""CLI envelope coverage for single and bounded Ouroboros review."""

from __future__ import annotations

import pytest

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_with_dispatch,
    _stub_dispatch_ok,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def test_single_entry_review_dispatches_global_target() -> None:
    rc = _run_with_dispatch(
        _stub_dispatch_ok,
        "ouroboros",
        "entry",
        "mark-reviewed",
        "31555",
    )

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "ouroboros.entry.mark_reviewed"
    assert request.target.kind == "global"
    assert request.payload == {"entry_id": 31555}


def test_bounded_field_note_review_dispatches_cutoff_and_limit() -> None:
    rc = _run_with_dispatch(
        _stub_dispatch_ok,
        "ouroboros",
        "entry",
        "mark-reviewed",
        "--field-notes-before",
        "2026-08-01",
        "--limit",
        "7",
    )

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "ouroboros.entry.mark_reviewed"
    assert request.target.kind == "global"
    assert request.payload == {
        "field_notes_before": "2026-08-01",
        "limit": 7,
    }


@pytest.mark.parametrize(
    "args",
    (
        ("31555", "--field-notes-before", "2026-08-01"),
        ("31555", "--limit", "7"),
        (),
    ),
)
def test_review_rejects_ambiguous_or_incomplete_selectors(
    args: tuple[str, ...],
) -> None:
    rc = _run_with_dispatch(
        _stub_dispatch_ok,
        "ouroboros",
        "entry",
        "mark-reviewed",
        *args,
    )

    assert rc == 2
    assert not _CAPTURED_REQUESTS
