"""A run's pinned commit, resolved against a checkout that may be behind.

A bound project's commit is pinned from its remote, so it routinely names a
commit the machine's own checkout has not fetched yet — a commit that exists
reads exactly like one that never did. These tests drive the real comparison
across real repositories: the pin that is at the remote must resolve, and the
pin that is nowhere must refuse by naming the project, the commit and the
place that looked, rather than a remedy belonging to a different failure.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.bound_source_release import (
    CONSUMER_PROJECT,
    two_project_release,
)
from runtime.api.fixtures.carried_release_candidate import (
    git,
    serve_repositories,
)
from yoke_core.domain import deployment_run_carried_work_repository as provider
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_membership import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_carried_work_source import (
    SOURCE_REPOSITORY_PROVIDER,
)


#: A well-formed commit id no repository in these tests has ever held.
ABSENT_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _clone(origin: Path, destination: Path) -> Path:
    """A checkout of ``origin`` that stops knowing it the moment it moves."""
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    return destination


def _holds(repo: Path, commit_sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{commit_sha}^{{commit}}"],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def _advance(repo: Path, message: str) -> str:
    (repo / "release.txt").write_text(f"{message}\n", encoding="utf-8")
    git(repo, "commit", "-am", message)
    return git(repo, "rev-parse", "HEAD")


def _stale_consumer_checkout(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], Path, str]:
    """A release whose bound pin landed after the local checkout last looked."""
    release = two_project_release(conn, tmp_path, monkeypatch)
    stale = _clone(release["consumer_repo"], tmp_path / "consumer-stale")
    published = _advance(release["consumer_repo"], "Land the follow-up work")
    serve_repositories(
        monkeypatch,
        {1: release["carrier_repo"], release["consumer_id"]: stale},
    )
    return release, stale, published


def _pin_consumer(conn: Any, release: dict[str, Any], commit_sha: str) -> None:
    conn.execute(
        "UPDATE deployment_runs SET bound_sources=%s WHERE id='run-candidate'",
        (
            json.dumps(
                {
                    "schema": 1,
                    "projects": [
                        {
                            "project": CONSUMER_PROJECT,
                            "project_id": release["consumer_id"],
                            "commit_sha": commit_sha,
                        }
                    ],
                    "inputs": {"consumer_sha": commit_sha},
                }
            ),
        ),
    )
    conn.commit()


def _bound_set(carried: dict[str, Any]) -> dict[str, Any]:
    return {
        entry["project"]: entry for entry in carried["bound_projects"]
    }[CONSUMER_PROJECT]


def test_a_pin_the_checkout_has_not_fetched_resolves_after_the_source_refreshes(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commit is published; only this checkout had not heard of it yet."""
    release, stale, published = _stale_consumer_checkout(
        test_db, tmp_path, monkeypatch
    )
    recorded = record_bound_sources(test_db, "run-candidate")
    test_db.commit()
    assert recorded["inputs"]["consumer_sha"] == published
    assert not _holds(stale, published)

    carried = derive_carried_work(test_db, "run-candidate")

    bound = _bound_set(carried)
    assert bound["derivation"]["contents_known"] is True
    assert bound["derivation"]["release_lineage"] == published
    assert published in bound["commits"] or any(
        published in entry["commit_shas"] for entry in bound["items"]
    )


def test_a_pin_no_source_holds_names_the_project_commit_and_checkout(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refresh that still cannot find it refuses with the facts it has."""
    release, stale, _published = _stale_consumer_checkout(
        test_db, tmp_path, monkeypatch
    )
    _pin_consumer(test_db, release, ABSENT_COMMIT)

    carried = derive_carried_work(test_db, "run-candidate")

    derivation = _bound_set(carried)["derivation"]
    assert derivation["reason"] == "current_release_lineage_unreachable"
    assert derivation["contents_known"] is False
    recovery = derivation["recovery"]
    assert CONSUMER_PROJECT in recovery
    assert ABSENT_COMMIT in recovery
    assert str(stale) in recovery
    # Attribution's remedy repairs a different failure and is not offered here.
    assert "composition_resolution" not in recovery


def test_the_membership_refusal_carries_the_recovery_the_reason_earned(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal an operator reads names the repair that applies to it."""
    release, stale, _published = _stale_consumer_checkout(
        test_db, tmp_path, monkeypatch
    )
    _pin_consumer(test_db, release, ABSENT_COMMIT)

    refusal = carried_membership_refusal(test_db, "run-candidate")

    assert refusal is not None
    assert "carried-code membership is current_release_lineage_unreachable" in refusal
    assert CONSUMER_PROJECT in refusal
    assert ABSENT_COMMIT in refusal
    assert str(stale) in refusal
    assert "repair attribution" not in refusal


class _UnfetchableSource:
    """A source with no checkout to refresh, answering only what it holds."""

    origin = SOURCE_REPOSITORY_PROVIDER
    location = "acme/consumer"

    def __init__(self, known: str) -> None:
        self._known = known

    def resolve_commit(self, ref: str) -> str:
        return ref if ref == self._known else ""

    def warnings(self) -> list[dict[str, str]]:
        return []


def test_a_source_that_cannot_fetch_refuses_without_naming_a_checkout(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host holding no checkout of the project is told what it can do.

    Refreshing is something a local checkout may be able to do, never a thing
    composition requires, so the host that has none still reaches the ordinary
    named refusal — and that refusal cannot send its reader to fetch a
    checkout that does not exist.
    """
    release = two_project_release(test_db, tmp_path, monkeypatch)
    serve_repositories(monkeypatch, {1: release["carrier_repo"]})
    monkeypatch.setattr(
        provider,
        "open_repository_provider_source",
        lambda _conn, _project_id: _UnfetchableSource(release["consumer_base"]),
    )
    _pin_consumer(test_db, release, ABSENT_COMMIT)

    carried = derive_carried_work(test_db, "run-candidate")

    derivation = _bound_set(carried)["derivation"]
    assert derivation["reason"] == "current_release_lineage_unreachable"
    recovery = derivation["recovery"]
    assert "acme/consumer" in recovery
    assert ABSENT_COMMIT in recovery
    assert "checkout" not in recovery
    assert "fetch" not in recovery
