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
        public_ref="YOK-42",
        warn=warnings.append,
    )

    assert seen == [
        {
            "repo": "acme/widgets",
            "run_id": "55",
            "kind": CI_WAIT_MERGE_VERIFICATION,
            "head_sha": "a" * 40,
            "continue_command": "yoke merge item YOK-42",
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


def test_a_failed_registration_is_surfaced_without_raising(monkeypatch):
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
        public_ref="YOK-42",
        warn=warnings.append,
    )

    assert warnings == [
        "ci wait not recorded: control plane refused; this run's verdict "
        "will not wake a stopped turn"
    ]
