"""CLI envelope coverage for Ouroboros review and archive close-out."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_with_dispatch,
    _stub_dispatch_ok,
)


_PROJECT_CONTEXT = "yoke_cli.commands.adapters.ouroboros_writes.client_project_context"


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(*argv: str, checkout_project: str | None = "yoke") -> int:
    """Run the CLI with a stubbed client-side project ladder.

    The real ladder reads ``--project``, ``YOKE_PROJECT``, then the machine
    checkout map, so it varies by where the suite runs. The stub keeps the
    explicit flag authoritative and pins only the ambient answer.
    """
    with patch(_PROJECT_CONTEXT, side_effect=lambda explicit=None: explicit or checkout_project):
        return _run_with_dispatch(_stub_dispatch_ok, *argv)


def test_single_entry_review_dispatches_global_target() -> None:
    rc = _run("ouroboros", "entry", "mark-reviewed", "31555")

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "ouroboros.entry.mark_reviewed"
    assert request.target.kind == "global"
    assert request.payload == {"entry_id": 31555, "project": "yoke"}


def test_single_entry_review_without_checkout_project_still_dispatches() -> None:
    """The entry row carries the write authority, so no project is required."""
    rc = _run("ouroboros", "entry", "mark-reviewed", "31555", checkout_project=None)

    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"entry_id": 31555}


def test_bounded_field_note_review_dispatches_cutoff_and_limit() -> None:
    rc = _run(
        "ouroboros", "entry", "mark-reviewed",
        "--field-notes-before", "2026-08-01",
        "--limit", "7",
    )

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "ouroboros.entry.mark_reviewed"
    assert request.target.kind == "global"
    assert request.payload == {
        "field_notes_before": "2026-08-01",
        "limit": 7,
        "project": "yoke",
    }


def test_bounded_all_category_review_dispatches_cutoff_and_limit() -> None:
    rc = _run(
        "ouroboros", "entry", "mark-reviewed",
        "--before", "2026-08-01",
        "--limit", "7",
        "--project", "externalwebapp",
    )

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.payload == {
        "before": "2026-08-01",
        "limit": 7,
        "project": "externalwebapp",
    }


def test_bounded_review_carries_the_unattributed_opt_in() -> None:
    rc = _run(
        "ouroboros", "entry", "mark-reviewed",
        "--before", "2026-08-01",
        "--include-unattributed",
    )

    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {
        "before": "2026-08-01",
        "include_unattributed": True,
        "project": "yoke",
    }


def test_bounded_review_without_a_project_is_refused() -> None:
    rc = _run(
        "ouroboros", "entry", "mark-reviewed",
        "--before", "2026-08-01",
        checkout_project=None,
    )

    assert rc == 2
    assert not _CAPTURED_REQUESTS


@pytest.mark.parametrize(
    "args",
    (
        ("31555", "--field-notes-before", "2026-08-01"),
        ("--before", "2026-08-01", "--field-notes-before", "2026-08-01"),
        ("31555", "--limit", "7"),
        ("31555", "--include-unattributed"),
        (),
    ),
)
def test_review_rejects_ambiguous_or_incomplete_selectors(
    args: tuple[str, ...],
) -> None:
    rc = _run("ouroboros", "entry", "mark-reviewed", *args)

    assert rc == 2
    assert not _CAPTURED_REQUESTS


def test_single_entry_archive_dispatches_entry_and_project() -> None:
    rc = _run("ouroboros", "entry", "mark-archived", "31555")

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "ouroboros.entry.mark_archived"
    assert request.payload == {
        "all_reviewed": False,
        "entry_id": 31555,
        "project": "yoke",
    }


def test_all_reviewed_archive_carries_the_unattributed_opt_in() -> None:
    rc = _run("ouroboros", "entry", "mark-archived", "--all-reviewed",
              "--include-unattributed")

    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {
        "all_reviewed": True,
        "include_unattributed": True,
        "project": "yoke",
    }


def test_all_reviewed_archive_without_a_project_is_refused() -> None:
    rc = _run(
        "ouroboros", "entry", "mark-archived", "--all-reviewed",
        checkout_project=None,
    )

    assert rc == 2
    assert not _CAPTURED_REQUESTS


def test_single_entry_archive_rejects_the_unattributed_opt_in() -> None:
    rc = _run("ouroboros", "entry", "mark-archived", "31555",
              "--include-unattributed")

    assert rc == 2
    assert not _CAPTURED_REQUESTS
