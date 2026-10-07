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
from yoke_core.domain.qa_requirement_target_rebind import rebind_requirement

BASE_URL = "https://distribution.example.test"
PINNED = "0.1.1+launch.590"
NEWER_LATEST = "0.1.1+launch.591"


def _pin_capability(conn: Any) -> None:
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "VALUES(1,'release_pin',%s,%s) ON CONFLICT(project_id,type) "
        "DO UPDATE SET settings=EXCLUDED.settings",
        (json.dumps({"desired_pin_path": "release.yoke_pin"}), "2026-10-07T00:00:00Z"),
    )
    conn.commit()


def _set_stage(conn: Any, settings: dict[str, Any]) -> None:
    _environment(conn)
    _edit_stage_settings(conn, settings)


def _stage_settings(pin: str | None) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "distribution": {"base_url": BASE_URL, "channel": "latest"}
    }
    if pin is not None:
        settings["release"] = {"yoke_pin": pin}
    return settings


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
    return [
        json.loads(row[0])
        for row in conn.execute(
            "SELECT execution_target_json FROM qa_requirements "
            "WHERE deployment_run_id=%s",
            (run_id,),
        ).fetchall()
    ]


def test_frozen_target_records_the_pinned_release_not_the_channel(test_db, monkeypatch):
    _pin_capability(test_db)
    _set_stage(test_db, _stage_settings(PINNED))
    fetched = _published(monkeypatch, PINNED, NEWER_LATEST)

    _materialized_stage(test_db, "run-release-version-pinned", 9821)

    targets = _frozen_targets(test_db, "run-release-version-pinned")
    assert targets
    for target in targets:
        assert target["endpoints"]["release_version"] == PINNED
        assert target["endpoints"]["release_channel"] == "latest"
    assert fetched == [
        deployment_qa_release_version.release_records_url(BASE_URL, PINNED)
    ]
    assert fetched[0] == (
        f"{BASE_URL}/dist/releases/0.1.1%2Blaunch.590/release-records.json"
    )


def test_unpublished_pinned_release_refuses_with_named_reason(test_db, monkeypatch):
    _pin_capability(test_db)
    _set_stage(test_db, _stage_settings(PINNED))
    _published(monkeypatch, NEWER_LATEST)

    with pytest.raises(ValueError, match="deployment_qa_release_unpublished") as exc:
        _materialized_stage(test_db, "run-release-version-unpublished", 9822)
    assert PINNED in str(exc.value)
    assert "re-run the QA stage" in str(exc.value)


def test_release_record_without_wheels_refuses(test_db, monkeypatch):
    _pin_capability(test_db)
    _set_stage(test_db, _stage_settings(PINNED))
    monkeypatch.setattr(deployment_qa_release_version, "_fetch", lambda url: b"[]")

    with pytest.raises(ValueError, match="lists no published wheels"):
        _materialized_stage(test_db, "run-release-version-empty", 9827)


def test_unreadable_installer_origin_refuses_as_unverified(test_db, monkeypatch):
    _pin_capability(test_db)
    _set_stage(test_db, _stage_settings(PINNED))

    def unreachable(url: str) -> bytes:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(deployment_qa_release_version, "_fetch", unreachable)

    with pytest.raises(ValueError, match="deployment_qa_release_unverified"):
        _materialized_stage(test_db, "run-release-version-unverified", 9823)


def test_missing_environment_pin_refuses_with_record_recovery(test_db, monkeypatch):
    _pin_capability(test_db)
    _set_stage(test_db, _stage_settings(None))
    _published(monkeypatch, PINNED)

    with pytest.raises(ValueError, match="deployment_qa_release_pin_missing") as exc:
        _materialized_stage(test_db, "run-release-version-missing", 9824)
    assert "yoke release-pin record" in str(exc.value)


def test_project_without_release_pin_capability_records_no_version(
    test_db, monkeypatch
):
    _set_stage(test_db, _stage_settings(PINNED))
    fetched = _published(monkeypatch)

    _materialized_stage(test_db, "run-release-version-unpinned", 9825)

    targets = _frozen_targets(test_db, "run-release-version-unpinned")
    assert targets
    assert all("release_version" not in t["endpoints"] for t in targets)
    assert fetched == []


def test_rebind_keeps_the_frozen_candidate_release(test_db, monkeypatch):
    _pin_capability(test_db)
    unset_channel = _stage_settings(PINNED)
    del unset_channel["distribution"]["channel"]
    _set_stage(test_db, unset_channel)
    _published(monkeypatch, PINNED)
    run_id = "run-release-version-rebind"
    _materialized_stage(test_db, run_id, 9826)
    _set_stage(test_db, _stage_settings(NEWER_LATEST))

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
