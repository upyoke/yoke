"""Deployment QA targets freeze the Yoke release the deployed candidate pins."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from runtime.api.domain.test_deployment_qa_frozen_target_authority import (
    _edit_stage_settings,
    _materialized_stage,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _environment
from yoke_core.domain import deployment_qa_release_version
from yoke_core.domain.project_file_at_commit import (
    ProjectFileAbsent,
    ProjectFileUnreadable,
)
from yoke_core.domain.qa_requirement_target_rebind import rebind_requirement

BASE_URL = "https://distribution.example.test"
PIN_FILE = "yoke-release-pin.txt"
PINNED = "0.1.1+launch.590"
NEWER = "0.1.1+launch.591"
CANDIDATE = "a" * 40  # the seeded run's release_lineage


def _pin_capability(conn: Any, project_id: int = 1, **extra: Any) -> None:
    settings = {"desired_pin_path": "release.yoke_pin", **extra}
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "VALUES(%s,'release_pin',%s,%s) ON CONFLICT(project_id,type) "
        "DO UPDATE SET settings=EXCLUDED.settings",
        (project_id, json.dumps(settings), "2026-10-07T00:00:00Z"),
    )
    conn.commit()


def _stage(conn: Any, *, channel: str | None = "latest", leaf: str = NEWER) -> None:
    """Stage settings whose desired-pin leaf a later release already moved."""
    distribution = {"base_url": BASE_URL}
    if channel is not None:
        distribution["channel"] = channel
    _environment(conn)
    _edit_stage_settings(
        conn, {"distribution": distribution, "release": {"yoke_pin": leaf}}
    )


def _candidate_files(monkeypatch, files: dict[tuple[str, str], str]) -> list:
    reads: list[tuple[int, str, str]] = []

    def read(conn: Any, project_id: int, sha: str, path: str) -> bytes:
        reads.append((project_id, sha, path))
        if (sha, path) not in files:
            raise ProjectFileAbsent(f"commit {sha} does not carry {path}")
        return files[(sha, path)].encode()

    monkeypatch.setattr(deployment_qa_release_version, "read_project_file", read)
    return reads


def _published(monkeypatch, *versions: str) -> list[str]:
    fetched: list[str] = []
    published = {
        deployment_qa_release_version.release_records_url(BASE_URL, v) for v in versions
    }

    def fetch(url: str) -> bytes:
        fetched.append(url)
        if url not in published:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO())
        return b'[{"filename": "yoke-0.1.1-py3-none-any.whl"}]'

    monkeypatch.setattr(deployment_qa_release_version, "_fetch", fetch)
    return fetched


def _frozen_targets(conn: Any, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT execution_target_json FROM qa_requirements WHERE deployment_run_id=%s",
        (run_id,),
    ).fetchall()
    assert rows
    return [json.loads(row[0]) for row in rows]


def test_frozen_target_reads_the_pin_at_the_deployed_candidate_commit(
    test_db, monkeypatch
):
    _pin_capability(test_db, candidate_pin_file=PIN_FILE)
    _stage(test_db)
    reads = _candidate_files(monkeypatch, {(CANDIDATE, PIN_FILE): f"{PINNED}\n"})
    fetched = _published(monkeypatch, PINNED, NEWER)

    _materialized_stage(test_db, "run-release-version-pinned", 9821)

    for target in _frozen_targets(test_db, "run-release-version-pinned"):
        # Neither the channel nor the environment leaf a later release moved.
        assert target["endpoints"]["release_version"] == PINNED
        assert target["endpoints"]["release_channel"] == "latest"
    assert set(reads) == {(1, CANDIDATE, PIN_FILE)}
    assert set(fetched) == {
        f"{BASE_URL}/dist/releases/0.1.1%2Blaunch.590/release-records.json"
    }


def test_bound_project_reads_the_release_pin_output_commit(test_db, monkeypatch):
    _pin_capability(test_db, project_id=2, candidate_pin_file=PIN_FILE)
    consumer, pin_commit = "b" * 40, "c" * 40
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at,bound_sources) VALUES(%s,1,'flow-bound',%s,'executing',%s,%s)",
        (
            "run-bound-consumer",
            CANDIDATE,
            "2026-10-07T00:00:00Z",
            json.dumps(
                {
                    "schema": 1,
                    "projects": [
                        {
                            "project": "consumer",
                            "project_id": 2,
                            "commit_sha": consumer,
                            "outputs": [
                                {
                                    "commit_sha": pin_commit,
                                    "reason": "release_pin_materialization",
                                }
                            ],
                        }
                    ],
                    "inputs": {"consumer_sha": consumer},
                }
            ),
        ),
    )
    reads = _candidate_files(monkeypatch, {(pin_commit, PIN_FILE): NEWER})
    _published(monkeypatch, NEWER)

    endpoints = deployment_qa_release_version.pinned_release_endpoints(
        test_db, "run-bound-consumer", 2, {"installer_base_url": BASE_URL}
    )

    assert endpoints["release_version"] == NEWER
    assert reads == [(2, pin_commit, PIN_FILE)]


def test_unpublished_pinned_release_refuses_with_named_reason(test_db, monkeypatch):
    _pin_capability(test_db, candidate_pin_file=PIN_FILE)
    _stage(test_db)
    _candidate_files(monkeypatch, {(CANDIDATE, PIN_FILE): PINNED})
    _published(monkeypatch, NEWER)

    with pytest.raises(ValueError, match="deployment_qa_release_unpublished") as exc:
        _materialized_stage(test_db, "run-release-version-unpublished", 9822)
    assert PINNED in str(exc.value)
    assert "re-run the QA stage" in str(exc.value)


def test_release_record_without_wheels_refuses(test_db, monkeypatch):
    _pin_capability(test_db, candidate_pin_file=PIN_FILE)
    _stage(test_db)
    _candidate_files(monkeypatch, {(CANDIDATE, PIN_FILE): PINNED})
    monkeypatch.setattr(deployment_qa_release_version, "_fetch", lambda url: b"[]")

    with pytest.raises(ValueError, match="lists no published wheels"):
        _materialized_stage(test_db, "run-release-version-empty", 9827)


def test_unreadable_installer_origin_refuses_as_unverified(test_db, monkeypatch):
    _pin_capability(test_db, candidate_pin_file=PIN_FILE)
    _stage(test_db)
    _candidate_files(monkeypatch, {(CANDIDATE, PIN_FILE): PINNED})

    def unreachable(url: str) -> bytes:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(deployment_qa_release_version, "_fetch", unreachable)

    with pytest.raises(ValueError, match="deployment_qa_release_unverified"):
        _materialized_stage(test_db, "run-release-version-unverified", 9823)


def test_candidate_without_the_pin_file_refuses(test_db, monkeypatch):
    _pin_capability(test_db, candidate_pin_file=PIN_FILE)
    _stage(test_db)
    _candidate_files(monkeypatch, {})
    _published(monkeypatch, PINNED)

    with pytest.raises(ValueError, match="deployment_qa_release_pin_missing") as exc:
        _materialized_stage(test_db, "run-release-version-missing", 9824)
    assert PIN_FILE in str(exc.value)


def test_unreadable_candidate_source_refuses_with_recovery(test_db, monkeypatch):
    _pin_capability(test_db, candidate_pin_file=PIN_FILE)
    _stage(test_db)

    def unreadable(*args: Any) -> bytes:
        raise ProjectFileUnreadable("no checkout; binding revoked")

    monkeypatch.setattr(deployment_qa_release_version, "read_project_file", unreadable)

    with pytest.raises(ValueError, match="deployment_qa_release_pin_unreadable") as exc:
        _materialized_stage(test_db, "run-release-version-unreadable", 9828)
    assert "yoke project register" in str(exc.value)


@pytest.mark.parametrize("declared", [False, True])
def test_no_declared_pin_file_records_no_version(test_db, monkeypatch, declared):
    if declared:
        _pin_capability(test_db)  # release_pin without candidate_pin_file
    _stage(test_db)
    reads = _candidate_files(monkeypatch, {})
    fetched = _published(monkeypatch)
    run_id = f"run-release-version-undeclared-{int(declared)}"

    _materialized_stage(test_db, run_id, 9825 + 10 * int(declared))

    assert all(
        "release_version" not in t["endpoints"]
        for t in _frozen_targets(test_db, run_id)
    )
    assert reads == [] and fetched == []


def test_invalid_pin_file_declaration_is_refused():
    from yoke_core.domain.release_pin_capability import validate_settings

    for bad in ("", "/abs/pin.txt", "../pin.txt", "a//b"):
        with pytest.raises(ValueError, match="candidate_pin_file"):
            validate_settings({"desired_pin_path": "a.b", "candidate_pin_file": bad})


def test_rebind_keeps_the_frozen_candidate_release(test_db, monkeypatch):
    _pin_capability(test_db, candidate_pin_file=PIN_FILE)
    _stage(test_db, channel=None)
    _candidate_files(monkeypatch, {(CANDIDATE, PIN_FILE): PINNED})
    _published(monkeypatch, PINNED)
    run_id = "run-release-version-rebind"
    _materialized_stage(test_db, run_id, 9826)
    _stage(test_db)

    for (requirement_id,) in test_db.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s", (run_id,)
    ).fetchall():
        rebind_requirement(
            test_db,
            requirement_id=int(requirement_id),
            rationale="distribution channel declared on the same environment",
            actor_id=2,
        )

    for target in _frozen_targets(test_db, run_id):
        assert target["endpoints"]["release_channel"] == "latest"
        assert target["endpoints"]["release_version"] == PINNED
