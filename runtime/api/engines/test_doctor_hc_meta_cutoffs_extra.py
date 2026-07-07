"""Cutoff tests for YOK-1704 task 3 — bespoke-scaffold HC cutoffs.

Sibling of ``test_doctor_hc_meta_cutoffs.py`` that owns the two HC
sources whose scaffolding does not fit the shared meta-fixture schema:

  * ``hc_cross_project_commits`` (asserts ``--since=`` flag plumbing on
    a mocked ``git log`` invocation), and
  * ``hc_offer_envelope_clobber_lost_chain`` (needs its own
    ``harness_sessions`` chain-state schema fixture).

Split out to keep each test file under the 350-line hard cap.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from yoke_core.domain import db_backend
from yoke_core.engines._doctor_hc_cutoff_test_helpers import (
    _patch_repo_root,
    _write_cutoff,
)
from yoke_core.engines._doctor_meta_test_helpers import (
    _args,
    _insert_item,
    _make_conn,
    _p,
    _results,
    _seed_project,
)
from yoke_core.engines.doctor import RecordCollector, hc_cross_project_commits
from yoke_core.engines.doctor_hc_routed_ownership import (
    hc_offer_envelope_clobber_lost_chain,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _make_completed(returncode=0, stdout="", stderr=""):
    """Create a mock subprocess.CompletedProcess."""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestCrossProjectCommitsCutoff:
    """``hc_cross_project_commits`` uses ``git log --since`` for the cutoff.

    ``_base._run`` is mocked so the test asserts the ``--since=<value>``
    flag is appended to the ``git log`` argv when the cutoff is set.
    """

    def _seed_done_non_yoke(self, conn, item_id: int, project: str) -> None:
        _seed_project(conn, project)
        _insert_item(
            conn, item_id, f"Item {item_id}", project=project,
            type="issue", status="done",
        )
        conn.commit()

    def test_cutoff_appends_since_flag(self, tmp_path):
        conn = _make_conn()
        self._seed_done_non_yoke(conn, item_id=999, project="buzz")
        cutoff = "2026-04-18"
        _write_cutoff(
            tmp_path, "hc_cross_project_commits_min_commit_date", cutoff,
        )

        captured_argv = []

        def fake_run(cmd, *_pos, **_kw):
            captured_argv.append(list(cmd))
            return _make_completed(returncode=0, stdout="")

        rec = RecordCollector()
        with _patch_repo_root(tmp_path), patch(
            "yoke_core.engines.doctor_report._run", side_effect=fake_run,
        ):
            hc_cross_project_commits(conn, _args(), rec)

        assert captured_argv, "expected git log to be invoked"
        assert any(arg == f"--since={cutoff}" for arg in captured_argv[0]), (
            f"expected --since={cutoff} flag, got {captured_argv[0]}"
        )

    def test_no_cutoff_omits_since_flag(self, tmp_path):
        conn = _make_conn()
        self._seed_done_non_yoke(conn, item_id=999, project="buzz")

        captured_argv = []

        def fake_run(cmd, *_pos, **_kw):
            captured_argv.append(list(cmd))
            return _make_completed(returncode=0, stdout="")

        rec = RecordCollector()
        with _patch_repo_root(tmp_path), patch(
            "yoke_core.engines.doctor_report._run", side_effect=fake_run,
        ):
            hc_cross_project_commits(conn, _args(), rec)

        assert captured_argv, "expected git log to be invoked"
        for arg in captured_argv[0]:
            assert not arg.startswith("--since="), (
                f"expected no --since flag, got {captured_argv[0]}"
            )


_CLOBBER_SCHEMA = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL DEFAULT 'claude-code',
    provider TEXT NOT NULL DEFAULT 'anthropic',
    model TEXT NOT NULL DEFAULT '',
    execution_lane TEXT NOT NULL DEFAULT 'primary',
    capabilities TEXT,
    workspace TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'wait',
    offered_at TEXT NOT NULL DEFAULT '',
    last_heartbeat TEXT NOT NULL DEFAULT '',
    ended_at TEXT,
    offer_envelope TEXT,
    actor_id INTEGER,
    last_chain_step INTEGER,
    last_checkpoint_at TEXT
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TEXT NOT NULL DEFAULT '',
    last_heartbeat TEXT NOT NULL DEFAULT '',
    released_at TEXT,
    release_reason TEXT
);
CREATE TABLE items (id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'idea');
"""


@pytest.fixture
def clobber_conn(tmp_path):
    def _apply_schema() -> None:
        c = db_backend.connect()
        try:
            apply_fixture_ddl(c, _CLOBBER_SCHEMA)
        finally:
            c.close()

    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


def _seed_clobber_session(conn, session_id: str, offered_at: str) -> None:
    """Seed a session that trips HC-offer-envelope-clobber-lost-chain.

    Chain progress is first-class state: ``last_chain_step=5`` with a live
    envelope carrying no ``chain_checkpoint`` is the clobbered shape.
    """
    p = _p(conn)
    base = datetime.fromisoformat(offered_at.replace("Z", "+00:00"))
    earlier = (base - timedelta(seconds=180)).isoformat()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, workspace, offered_at, last_heartbeat, offer_envelope, "
        " last_chain_step, last_checkpoint_at) "
        f"VALUES ({p}, '/tmp', {p}, {p}, {p}, 5, {p})",
        (session_id, offered_at, offered_at, json.dumps({"step": 7}), earlier),
    )
    conn.commit()


class TestOfferEnvelopeClobberCutoff:
    def test_below_cutoff_excluded(self, clobber_conn, tmp_path):
        _seed_clobber_session(
            clobber_conn, "sess-old", offered_at="2026-04-01T00:00:00+00:00",
        )
        _seed_clobber_session(
            clobber_conn, "sess-new", offered_at="2026-05-14T00:00:00+00:00",
        )
        _write_cutoff(
            tmp_path,
            "hc_offer_envelope_clobber_min_session_created_at",
            "2026-05-13T17:40:59+00:00",
        )

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_offer_envelope_clobber_lost_chain(clobber_conn, _args(), rec)

        result, detail = _results(rec)[
            "HC-offer-envelope-clobber-lost-chain"
        ]
        assert result == "WARN"
        assert "sess-old" not in detail
        assert "sess-new" in detail

    def test_no_cutoff_keeps_legacy_behavior(self, clobber_conn, tmp_path):
        _seed_clobber_session(
            clobber_conn, "sess-old", offered_at="2026-04-01T00:00:00+00:00",
        )

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_offer_envelope_clobber_lost_chain(clobber_conn, _args(), rec)

        result, detail = _results(rec)[
            "HC-offer-envelope-clobber-lost-chain"
        ]
        assert result == "WARN"
        assert "sess-old" in detail
