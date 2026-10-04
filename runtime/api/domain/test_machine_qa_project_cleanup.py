"""Case ownership and retirement cleanup for passing and failing walks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.qa_project_ownership import OWNER_FILE, OWNER_CAPABILITY
from yoke_core.domain import machine_qa_project_cleanup as cleanup
from yoke_core.domain.machine_qa_project_ownership import assert_owner, mark_owner
from yoke_core.domain.db_helpers import connect
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_cli.config.qa_project_ownership import test_project_owner as read_owner


@pytest.fixture
def marker(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    p = tmp_path / ".yoke" / OWNER_FILE
    p.parent.mkdir()
    p.write_text(json.dumps({"owner": "case-1"}))
    return p


@pytest.mark.parametrize("case_verdict", ["pass", "fail"])
def test_case_finish_retires_only_owned_projects(marker, monkeypatch, case_verdict):
    calls = []

    def call(argv):
        calls.append(argv)
        if argv[:2] == ["projects", "list"]:
            return {"rows": [{"id": 1, "slug": "real"}, {"id": 2, "slug": "test"}]}
        if argv[:2] == ["projects", "capability-settings"]:
            return {
                "settings_json": json.dumps(
                    {"owner": "case-1" if argv[4] == "2" else "other"}
                )
            }
        return {"changed": True}

    monkeypatch.setattr(cleanup, "_call", call)
    assert read_owner() == "case-1"
    result = cleanup.cleanup("case-1", OWNER_FILE, OWNER_CAPABILITY)
    assert result["retired_projects"] == ["test"]
    retire_calls = [argv for argv in calls if argv[:2] == ["projects", "retire"]]
    assert len(retire_calls) == 1 and retire_calls[0][3] == "2"
    assert not marker.exists(), case_verdict


def test_retirement_blocker_keeps_owner_marker_and_names_recovery(marker, monkeypatch):
    def call(argv):
        if argv[:2] == ["projects", "list"]:
            return {"rows": [{"id": 2, "slug": "test"}]}
        if argv[:2] == ["projects", "capability-settings"]:
            return {"settings_json": '{"owner":"case-1"}'}
        raise RuntimeError(
            "project_retirement_blocked: held claim 42; release hold and retry"
        )

    monkeypatch.setattr(cleanup, "_call", call)
    with pytest.raises(RuntimeError, match="held claim 42"):
        cleanup.cleanup("case-1", OWNER_FILE, OWNER_CAPABILITY)
    assert marker.exists()


def test_another_case_owner_is_never_removed(marker):
    with pytest.raises(RuntimeError, match="another case owns"):
        cleanup.cleanup("case-2", OWNER_FILE, OWNER_CAPABILITY)
    assert marker.exists()


def test_preinstallation_teardown_needs_no_product_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert cleanup.cleanup("case-1", OWNER_FILE, OWNER_CAPABILITY)[
        "owner_marker_removed"
    ]


def test_durable_owner_cannot_take_over_existing_project(tmp_path):
    with init_test_db(tmp_path):
        conn = connect()
        try:
            with pytest.raises(ValueError, match="qa_project_owner_conflict"):
                assert_owner(conn, {"id": 1}, "case-1")
            mark_owner(conn, 1, "case-1")
            assert_owner(conn, {"id": 1}, "case-1")
            with pytest.raises(ValueError, match="qa_project_owner_conflict"):
                assert_owner(conn, {"id": 1}, "case-2")
        finally:
            conn.close()
