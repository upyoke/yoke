"""Slug/path helpers and the top-level ``qa.main`` CLI entrypoint."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import qa
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.qa_test_helpers import make_qa_db_file


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


class TestHelpers:
    def test_route_slug(self) -> None:
        assert qa._route_slug("/settings/profile") == "settings-profile"
        assert qa._route_slug("/") == ""
        assert qa._route_slug("/Dashboard") == "dashboard"

    def test_baseline_path(self) -> None:
        assert qa._baseline_path("/settings/profile", 1920, 1080) == "test/baselines/settings-profile-1920x1080.png"


class TestCLI:
    def test_no_subcmd_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.main([])
        assert exc.value.code == 2

    def test_init_via_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with init_test_db(tmp_path, apply_schema=lambda: None) as db_file:
            monkeypatch.setenv("YOKE_DB", db_file)
            qa.main(["init"])

    def test_requirement_list_via_cli(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        qa.cmd_requirement_add(db_path=db_path, item_id=42, qa_kind="test", qa_phase="verification")
        monkeypatch.setenv("YOKE_DB", db_path)
        lines = qa.cmd_requirement_list(item_id=42, db_path=db_path)
        assert len(lines) == 1

    def test_requirement_add_help_lists_policy_shapes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.main(["requirement-add", "--help"])

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--requirement-source" in out
        for source in qa.VALID_REQUIREMENT_SOURCES:
            assert source in out
        assert "browser_smoke" in out
        assert "browser_diff" in out
        assert '{"steps"' in out
        assert "ac_verification" in out
        assert "min_runs" in out

    def test_requirement_add_rejects_bad_source_before_db_write(
        self,
        db_path: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)

        with pytest.raises(SystemExit) as exc:
            qa.main([
                "requirement-add",
                "--item-id",
                "42",
                "--qa-kind",
                "ac_verification",
                "--qa-phase",
                "verification",
                "--requirement-source",
                "agent",
            ])

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "invalid choice" in err
        for source in qa.VALID_REQUIREMENT_SOURCES:
            assert source in err
        assert "sqlite3.IntegrityError" not in err
        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM qa_requirements").fetchone()[0]
        conn.close()
        assert count == 0

    def test_requirement_add_rejects_browser_policy_before_db_write(
        self,
        db_path: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)

        with pytest.raises(SystemExit) as exc:
            qa.main([
                "requirement-add",
                "--item-id",
                "42",
                "--qa-kind",
                "browser_smoke",
                "--qa-phase",
                "verification",
            ])

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "--success-policy is required when --qa-kind=browser_smoke" in err
        assert '{"steps"' in err
        assert "sqlite3.IntegrityError" not in err
        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM qa_requirements").fetchone()[0]
        conn.close()
        assert count == 0

    def test_requirement_add_rejects_browser_policy_shape_before_db_write(
        self,
        db_path: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)

        with pytest.raises(SystemExit) as exc:
            qa.main([
                "requirement-add",
                "--item-id",
                "42",
                "--qa-kind",
                "browser_smoke",
                "--qa-phase",
                "verification",
                "--success-policy",
                '{"steps":[{"route":"/"}]}',
            ])

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "missing the 'action' field" in err
        assert "sqlite3.IntegrityError" not in err
        conn = connect_test_db(db_path)
        count = conn.execute("SELECT COUNT(*) FROM qa_requirements").fetchone()[0]
        conn.close()
        assert count == 0
