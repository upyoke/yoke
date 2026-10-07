"""A failure caused by a frozen bound source says a new run is required.

The run keeps the bound commit it resolved at start, and a retry copies it,
so once the bound branch has moved a failure naming that commit reproduces on
every re-drive. These tests freeze a real bound commit, move the real branch,
and read the diagnosis a failure trace carries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.bound_source_release import (
    CONSUMER_PROJECT,
    two_project_release,
)
from runtime.api.fixtures.carried_release_candidate import git
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_release_output_record import (
    record_release_output,
)
from yoke_core.domain.deployment_run_stale_bound_sources import (
    check_bound_sources_current,
    diagnose_stale_bound_sources,
)


def _frozen_then_moved(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    release = two_project_release(conn, tmp_path, monkeypatch)
    record_bound_sources(conn, "run-candidate")
    conn.commit()
    repo = release["consumer_repo"]
    git(repo, "commit", "--allow-empty", "-m", "Consumer trunk moves on")
    current = git(repo, "rev-parse", "HEAD").strip()
    return release["consumer_tip"], current


def test_a_failure_naming_the_frozen_commit_says_a_new_run_is_required(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen, current = _frozen_then_moved(test_db, tmp_path, monkeypatch)

    stale, unverified = diagnose_stale_bound_sources(
        test_db,
        "run-candidate",
        failure_text=f"main moved, but the pair was proven at {frozen}.",
    )

    assert unverified == ""
    assert len(stale) == 1
    entry = stale[0]
    assert entry["project"] == CONSUMER_PROJECT
    assert entry["frozen_sha"] == frozen
    assert entry["current_sha"] == current
    assert entry["reason"].startswith(
        f"bound source {CONSUMER_PROJECT} {frozen} is stale (current {current}); "
        "re-driving run-candidate cannot pass"
    )
    assert "create a new run" in entry["reason"]


def test_an_unrelated_failure_is_not_blamed_on_the_moved_source(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _frozen_then_moved(test_db, tmp_path, monkeypatch)

    stale, unverified = diagnose_stale_bound_sources(
        test_db, "run-candidate", failure_text="unit tests failed: 3 errors"
    )

    assert (stale, unverified) == ([], "")


def test_a_frozen_commit_still_current_is_not_stale(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    test_db.commit()
    frozen = release["consumer_tip"]

    stale, unverified = diagnose_stale_bound_sources(
        test_db, "run-candidate", failure_text=f"pair refused at {frozen}"
    )

    assert (stale, unverified) == ([], "")


def test_an_unreadable_current_commit_is_named_rather_than_called_current(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen, _current = _frozen_then_moved(test_db, tmp_path, monkeypatch)
    from yoke_core.domain import deployment_run_stale_bound_sources as module

    def unreadable(*_args: Any, **_kwargs: Any) -> str:
        raise ValueError("could not resolve branch 'main'")

    monkeypatch.setattr(module, "_resolve_branch_head", unreadable)

    stale, unverified = diagnose_stale_bound_sources(
        test_db, "run-candidate", failure_text=f"proven at {frozen}"
    )

    assert stale == []
    assert unverified == (
        f"bound source {CONSUMER_PROJECT} {frozen}: could not resolve branch 'main'"
    )


def test_before_dispatch_a_moved_branch_is_stale_whatever_any_failure_says(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen, current = _frozen_then_moved(test_db, tmp_path, monkeypatch)

    stale, unverified = check_bound_sources_current(test_db, "run-candidate")

    assert unverified == ""
    assert [(e["project"], e["frozen_sha"], e["current_sha"]) for e in stale] == [
        (CONSUMER_PROJECT, frozen, current)
    ]
    assert "create a new run" in stale[0]["reason"]


def test_before_dispatch_an_unmoved_branch_is_current(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    test_db.commit()

    assert check_bound_sources_current(test_db, "run-candidate") == ([], "")


def test_before_dispatch_an_unreadable_head_is_named_not_assumed_current(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen, _current = _frozen_then_moved(test_db, tmp_path, monkeypatch)
    from yoke_core.domain import deployment_run_stale_bound_sources as module

    def unreadable(*_args: Any, **_kwargs: Any) -> str:
        raise ValueError("could not resolve branch 'main'")

    monkeypatch.setattr(module, "_resolve_branch_head", unreadable)

    stale, unverified = check_bound_sources_current(test_db, "run-candidate")

    assert stale == []
    assert unverified == (
        f"bound source {CONSUMER_PROJECT} {frozen}: could not resolve branch 'main'"
    )


def _pin_recorded_as_release_output(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, extra: bool
) -> tuple[str, str]:
    """A release's own pin commit lands on the frozen source, maybe with more."""
    release = two_project_release(conn, tmp_path, monkeypatch)
    record_bound_sources(conn, "run-candidate")
    conn.commit()
    repo = release["consumer_repo"]
    git(repo, "commit", "--allow-empty", "-m", "Pin the released version")
    if extra:
        git(repo, "commit", "--allow-empty", "-m", "Unrelated work after the pin")
    record_release_output(conn, run_id="run-candidate", project=CONSUMER_PROJECT)
    conn.commit()
    return release["consumer_tip"], git(repo, "rev-parse", "HEAD").strip()


def test_a_release_pin_written_directly_on_the_frozen_source_is_current(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_recorded_as_release_output(test_db, tmp_path, monkeypatch, extra=False)

    assert check_bound_sources_current(test_db, "run-candidate") == ([], "")


def test_release_output_not_directly_on_the_frozen_source_stays_stale(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen, current = _pin_recorded_as_release_output(
        test_db, tmp_path, monkeypatch, extra=True
    )

    stale, unverified = check_bound_sources_current(test_db, "run-candidate")

    assert unverified == ""
    assert [(e["frozen_sha"], e["current_sha"]) for e in stale] == [(frozen, current)]
