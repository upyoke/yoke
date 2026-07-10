"""Tests for the GitHub backlog sync allow-unclaimed ownership guard."""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import patch

import pytest

from runtime.api.backlog_github_sync_test_helpers import make_db as _make_db
from runtime.api.conftest import insert_item
from yoke_core.domain import db_backend
from yoke_core.domain import backlog_github_sync as _bgs
from yoke_core.domain import backlog_github_sync_cli as cli
from yoke_core.domain import backlog_github_body_budget as body_budget
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.api import service_client_backlog_github as relay


_OK_AUTH = ProjectGithubAuth(
    project="buzz", repo="org/buzz", token="ghs_fake",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_item(conn: Any, item_id: int) -> None:
    insert_item(
        conn, id=item_id, type="issue", status="implementing",
        project="buzz", github_issue=f"#{1000 + item_id}", spec="# stub spec",
    )


def _ensure_session(conn: Any, session_id: str) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, offered_at, "
        " last_heartbeat) VALUES "
        f"({p}, 'claude-code', 'anthropic', '', '/tmp', "
        " '2026-05-17T13:00:00Z', '2026-05-17T13:00:00Z') "
        "ON CONFLICT(session_id) DO NOTHING",
        (session_id,),
    )


def _seed_claim(conn: Any, *, item_id: int, session_id: str,
                released: bool = False) -> None:
    _ensure_session(conn, session_id)
    p = _p(conn)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, "
        " last_heartbeat, released_at) "
        f"VALUES ({p}, 'item', {p}, 'exclusive', "
        f"'2026-05-17T13:00:00Z', '2026-05-17T13:00:00Z', {p})",
        (session_id, item_id, "2026-05-17T13:05:00Z" if released else None),
    )
    conn.commit()


def _huge_spec() -> str:
    return "a" * (body_budget.GITHUB_BODY_BUDGET_BYTES + 5000)


@pytest.fixture()
def db_with_open_conn(monkeypatch):
    conn = _make_db()
    monkeypatch.setattr(cli, "_open_conn", lambda existing: (conn, False))
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cli, "_dry_run", lambda: False)


class TestCheckOwnership:
    def test_allow_when_no_claim(self, db_with_open_conn, monkeypatch):
        _seed_item(db_with_open_conn, 50)
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")
        allow, reason, holder = cli.check_ownership("BUZ-50")
        assert allow is True
        assert reason == "no-claim"
        assert holder == ""

    def test_allow_when_session_owns(self, db_with_open_conn, monkeypatch):
        _seed_item(db_with_open_conn, 51)
        _seed_claim(db_with_open_conn, item_id=51, session_id="session-A")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")
        allow, reason, holder = cli.check_ownership("51")
        assert allow is True
        assert reason == "self-owned"
        assert holder == "session-A"

    def test_deny_when_other_session_holds(
        self, db_with_open_conn, monkeypatch
    ):
        _seed_item(db_with_open_conn, 52)
        _seed_claim(db_with_open_conn, item_id=52, session_id="session-B")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")
        allow, reason, holder = cli.check_ownership("YOK-52")
        assert allow is False
        assert reason == "other-holder"
        assert holder == "session-B"

    def test_allow_when_only_released_claim(
        self, db_with_open_conn, monkeypatch
    ):
        _seed_item(db_with_open_conn, 53)
        _seed_claim(
            db_with_open_conn, item_id=53,
            session_id="session-B", released=True,
        )
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")
        allow, _reason, _holder = cli.check_ownership("53")
        assert allow is True

    def test_allow_when_holder_session_ended(self, db_with_open_conn, monkeypatch):
        _seed_item(db_with_open_conn, 55)
        _seed_claim(db_with_open_conn, item_id=55, session_id="session-B")
        db_with_open_conn.execute(
            "UPDATE harness_sessions SET ended_at = '2026-05-17T13:10:00Z' WHERE session_id = 'session-B'"
        )
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")
        assert cli.check_ownership("55") == (True, "holder-ended", "session-B")

    def test_dry_run_short_circuits(self, db_with_open_conn, monkeypatch):
        _seed_item(db_with_open_conn, 54)
        _seed_claim(db_with_open_conn, item_id=54, session_id="session-B")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")
        monkeypatch.setattr(cli, "_dry_run", lambda: True)
        allow, reason, _holder = cli.check_ownership("54")
        assert allow is True
        assert reason == "dry-run"


class TestDirectCliGuard:
    def test_sync_body_denied_before_gh_call(
        self, db_with_open_conn, monkeypatch, capsys
    ):
        _seed_item(db_with_open_conn, 60)
        _seed_claim(db_with_open_conn, item_id=60, session_id="session-B")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")

        called: list[str] = []
        with patch.object(
            _bgs, "sync_body",
            side_effect=lambda *a, **k: (called.append("sync_body"), 0)[1],
        ):
            rc = cli.main(["sync-body", "BUZ-60"])

        assert rc == 1
        assert called == []
        err = capsys.readouterr().err
        assert "Refusing to sync body" in err
        assert "session-B" in err

    def test_sync_title_denied(
        self, db_with_open_conn, monkeypatch, capsys
    ):
        _seed_item(db_with_open_conn, 61)
        _seed_claim(db_with_open_conn, item_id=61, session_id="session-B")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")

        called: list[str] = []
        with patch.object(
            _bgs, "sync_title",
            side_effect=lambda *a, **k: (called.append("sync_title"), 0)[1],
        ):
            rc = cli.main(["sync-title", "61"])

        assert rc == 1
        assert called == []
        assert "Refusing to sync title" in capsys.readouterr().err

    def test_self_owned_sync_body_proceeds(
        self, db_with_open_conn, monkeypatch
    ):
        _seed_item(db_with_open_conn, 62)
        _seed_claim(db_with_open_conn, item_id=62, session_id="session-A")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")

        called: list[str] = []
        with patch.object(
            _bgs, "sync_body",
            side_effect=lambda *args, **k: (called.append(args[0]), 0)[1],
        ):
            rc = cli.main(["sync-body", "62"])

        assert rc == 0
        assert called == ["62"]

    def test_unclaimed_sync_item_proceeds(
        self, db_with_open_conn, monkeypatch
    ):
        _seed_item(db_with_open_conn, 63)
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")

        called: list[str] = []
        with patch.object(
            _bgs, "sync_item",
            side_effect=lambda *args, **k: (called.append(args[0]), 0)[1],
        ):
            rc = cli.main(["sync-item", "63"])

        assert rc == 0
        assert called == ["63"]

    def test_dry_run_sync_body_skips_guard(
        self, db_with_open_conn, monkeypatch
    ):
        _seed_item(db_with_open_conn, 64)
        _seed_claim(db_with_open_conn, item_id=64, session_id="session-B")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")
        monkeypatch.setattr(cli, "_dry_run", lambda: True)

        called: list[str] = []
        with patch.object(
            _bgs, "sync_body",
            side_effect=lambda *args, **k: (called.append(args[0]), 0)[1],
        ):
            rc = cli.main(["sync-body", "64"])

        assert rc == 0
        assert called == ["64"]


class TestRelayGuard:
    def test_relay_sync_body_denied(
        self, db_with_open_conn, monkeypatch, capsys
    ):
        _seed_item(db_with_open_conn, 70)
        _seed_claim(db_with_open_conn, item_id=70, session_id="session-B")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")

        called: list[str] = []
        with patch.object(
            _bgs, "sync_body",
            side_effect=lambda *a, **k: (called.append("sync_body"), 0)[1],
        ):
            rc = relay.cmd_backlog_github(["sync-body", "BUZ-70"])

        assert rc == 1
        assert called == []
        err = capsys.readouterr().err
        assert "Refusing to sync body" in err
        assert "session-B" in err

    def test_relay_self_owned_sync_item_proceeds(
        self, db_with_open_conn, monkeypatch
    ):
        _seed_item(db_with_open_conn, 71)
        _seed_claim(db_with_open_conn, item_id=71, session_id="session-A")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")

        called: list[str] = []
        with patch.object(
            _bgs, "sync_item",
            side_effect=lambda *args, **k: (called.append(args[0]), 0)[1],
        ), patch(
            "yoke_core.domain.backlog._maybe_rebuild_board",
            return_value=None,
        ):
            rc = relay.cmd_backlog_github(["sync-item", "71"])

        assert rc == 0
        assert called == ["71"]


class TestBackfillOwnership:
    def test_backfill_skips_claimed_by_other(self, monkeypatch):
        db = _make_db()
        for item_id, issue in ((80, "#180"), (81, "#181"), (82, "#182")):
            insert_item(
                db, id=item_id, type="issue", status="implementing",
                project="buzz", github_issue=issue, spec=_huge_spec(),
            )
        insert_item(
            db, id=83, type="issue", status="implementing", project="buzz",
            github_issue="#183", spec="# small",
        )
        _seed_claim(db, item_id=81, session_id="session-A")
        _seed_claim(db, item_id=82, session_id="session-B")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")

        stdout = io.StringIO()
        stderr = io.StringIO()
        sync_calls: list[str] = []
        with patch.object(
            _bgs, "sync_body",
            side_effect=lambda i, **_k: (sync_calls.append(str(i)), 0)[1],
        ), patch.object(
            cli, "resolve_project_github_auth", return_value=_OK_AUTH,
        ):
            rc = cli.backfill_oversized_bodies(
                conn=db, stdout=stdout, stderr=stderr
            )

        # Claim-skip alone does not fail the batch.
        assert rc == 0
        # Item 82 is claimed by another live session and is skipped
        # before sync_body is called; items 80 and 81 are repaired.
        assert sorted(sync_calls) == ["80", "81"]
        out = stdout.getvalue()
        err = stderr.getvalue()
        assert "skipped_claimed 1" in out
        assert "BUZ-82 skipped_claimed" in err
        assert "session-B" in err
        # Small item (83) never appears in the repair output.
        assert "BUZ-83" not in out and "BUZ-83" not in err

    def test_backfill_dry_run_skips_guard(self, monkeypatch):
        db = _make_db()
        insert_item(
            db, id=84, type="issue", status="implementing", project="buzz",
            github_issue="#184", spec=_huge_spec(),
        )
        _seed_claim(db, item_id=84, session_id="session-B")
        monkeypatch.setenv("YOKE_SESSION_ID", "session-A")
        monkeypatch.setattr(cli, "_dry_run", lambda: True)

        stdout = io.StringIO()
        stderr = io.StringIO()
        sync_calls: list[str] = []
        with patch.object(
            _bgs, "sync_body",
            side_effect=lambda i, **_k: (sync_calls.append(str(i)), 0)[1],
        ), patch.object(
            cli, "resolve_project_github_auth", return_value=_OK_AUTH,
        ):
            rc = cli.backfill_oversized_bodies(
                conn=db, stdout=stdout, stderr=stderr
            )

        assert rc == 0
        # Dry-run bypasses the guard so the claimed-by-other item is repaired.
        assert sync_calls == ["84"]
        assert "skipped_claimed 0" in stdout.getvalue()
