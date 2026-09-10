"""Durable CI wait registration for the merge boundary's own verification."""

from __future__ import annotations

from yoke_core.domain import merge_ci_verification_wait
from yoke_core.domain.session_ci_wait_schema import CI_WAIT_MERGE_VERIFICATION


def test_records_the_exact_continuation_for_a_named_item(monkeypatch):
    seen = []
    monkeypatch.setattr(
        merge_ci_verification_wait,
        "record_ci_run_wait",
        lambda **kwargs: seen.append(kwargs) or "",
    )
    warnings = []

    merge_ci_verification_wait.record_wait_and_warn(
        repo="acme/widgets",
        run_id="55",
        head_sha="a" * 40,
        public_ref="ACME-9",
        warn=warnings.append,
    )

    assert seen == [
        {
            "repo": "acme/widgets",
            "run_id": "55",
            "kind": CI_WAIT_MERGE_VERIFICATION,
            "head_sha": "a" * 40,
            "continue_command": "yoke merge item ACME-9",
            "supersedes_run_id": "",
        }
    ]
    assert warnings == []


def test_an_unresolved_item_records_no_guessed_continuation(monkeypatch):
    seen = []
    monkeypatch.setattr(
        merge_ci_verification_wait,
        "record_ci_run_wait",
        lambda **kwargs: seen.append(kwargs) or "",
    )

    merge_ci_verification_wait.record_wait_and_warn(
        repo="acme/widgets",
        run_id="55",
        head_sha="a" * 40,
        public_ref="",
        warn=lambda _msg: None,
    )

    assert seen[0]["continue_command"] == ""


def test_a_failed_registration_names_the_exact_run_to_rejoin(monkeypatch):
    """A registration failure warns without raising and still teaches recovery."""
    monkeypatch.setattr(
        merge_ci_verification_wait,
        "record_ci_run_wait",
        lambda **_kwargs: "ci wait not recorded: control plane refused",
    )
    warnings = []

    merge_ci_verification_wait.record_wait_and_warn(
        repo="acme/widgets",
        run_id="55",
        head_sha="a" * 40,
        public_ref="ACME-9",
        warn=warnings.append,
    )

    assert warnings == [
        "ci wait not recorded: control plane refused; this run's verdict "
        "will not wake a stopped turn — re-run `yoke merge item ACME-9` to "
        "rejoin run 55 by exact commit and adopt its conclusion instead of "
        "dispatching another suite"
    ]


def test_a_failed_registration_with_no_item_still_names_the_run(monkeypatch):
    """An unresolved public_ref still gives a generic, runnable recovery."""
    monkeypatch.setattr(
        merge_ci_verification_wait,
        "record_ci_run_wait",
        lambda **_kwargs: "ci wait not recorded: control plane refused",
    )
    warnings = []

    merge_ci_verification_wait.record_wait_and_warn(
        repo="acme/widgets",
        run_id="55",
        head_sha="a" * 40,
        public_ref="",
        warn=warnings.append,
    )

    assert "re-run the same `yoke merge item` command" in warnings[0]
    assert "run 55" in warnings[0]
