"""Tests for the first-class strategy rendered-view freshness deny.

The field-note-12882 fold-in: the commit-time rule fires per staged
file, BEFORE the ``# lint:no-main-check`` suppression, independent of
in-flight worktree items, fail-closed on row-read failure — and the
merge preflight (PF-7) refuses incoming branch drift with the same
classification. The 12959 transport fold-in (rows resolve through the
dispatcher, one ``strategy.render.run`` riding the active transport) is
covered by the https-shaped sibling,
``test_lint_main_commit_strategy_freshness_https.py``, which imports
this module's fixtures.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_contracts.hook_runner.main_commit import (
    CLIENT_GIT_COMMIT_FACTS_KEY,
    CLIENT_GIT_COMMIT_FACTS_SCHEMA,
)
from yoke_core.domain import lint_main_commit as lint
from yoke_core.domain import lint_main_commit_process_claims as claims_helper
from yoke_core.domain import lint_main_commit_strategy_freshness as freshness
from yoke_core.domain.strategy_docs_header import (
    content_sha256,
    parse_file_text,
    render_file_text,
)
from yoke_core.domain.strategy_docs_paths import strategy_view_rel_path
from yoke_core.domain.strategy_docs_test_helpers import (
    PROJECT_A,
    SEED_CONTENT,
    SEED_UPDATED_AT,
    seed_docs,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

MISSION_REL = strategy_view_rel_path("MISSION")

FRESH_MISSION = render_file_text(
    "MISSION", SEED_UPDATED_AT, SEED_CONTENT["MISSION"],
)
EDITED_MISSION = render_file_text(
    "MISSION", SEED_UPDATED_AT, SEED_CONTENT["MISSION"],
).replace("Line two.", "scribbled without ingest.")


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            # The dispatcher-backed loader resolves target.project_id
            # against the projects table server-side (the schema seed may
            # already carry the default project row).
            conn.execute(
                "INSERT INTO projects (id, slug, name, created_at) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (PROJECT_A, "alpha", "Alpha", "2026-01-01T00:00:00Z"),
            )
            conn.commit()
            seed_docs(conn, PROJECT_A)
        finally:
            conn.close()
        yield db_path


def _payload(command: str) -> dict:
    return {"tool_input": {"command": command}}


def _client_strategy_fact(path: str, file_text: str) -> dict:
    parsed = parse_file_text(file_text)
    return {
        "path": path,
        "slug": path.rsplit("/", 1)[-1].removesuffix(".md"),
        "source": "index",
        "header_slug": parsed.slug,
        "header_updated_at": parsed.updated_at,
        "header_content_sha256": parsed.content_sha256,
        "body_sha256": content_sha256(parsed.body),
    }


def _client_payload(
    command: str,
    paths: list[str],
    *,
    strategy_blobs: list[dict] | None = None,
) -> dict:
    payload = _payload(command)
    payload[CLIENT_GIT_COMMIT_FACTS_KEY] = {
        "schema": CLIENT_GIT_COMMIT_FACTS_SCHEMA,
        "is_git_commit": True,
        "project_context": str(PROJECT_A),
        "branch": "main",
        "staged_paths": paths,
        "worktree_content_paths": [],
        "strategy_blobs": strategy_blobs or [],
    }
    return payload


@pytest.fixture
def commit_world(tmp_db: str, monkeypatch: pytest.MonkeyPatch):
    """evaluate_payload world: on main, project mapped, blobs patchable."""
    monkeypatch.setattr(lint, "_current_branch", lambda: "main")
    monkeypatch.setattr(
        claims_helper, "_commit_repo_project_context", lambda: str(PROJECT_A),
    )
    blobs: dict = {}
    monkeypatch.setattr(claims_helper, "_staged_blob", blobs.get)
    staged: list = []
    monkeypatch.setattr(lint, "_staged_files", lambda: list(staged))
    return SimpleNamespace(blobs=blobs, staged=staged)


class TestCommitDeny:
    def test_client_facts_block_impl_without_server_git(
        self, tmp_db: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            lint,
            "_current_branch",
            lambda: pytest.fail("client facts should supply branch"),
        )
        monkeypatch.setattr(
            lint,
            "_staged_files",
            lambda: pytest.fail("client facts should supply staged paths"),
        )
        monkeypatch.setattr(
            lint,
            "_active_worktree_items",
            lambda: ["42|Some item"],
        )
        reason = lint.evaluate_payload(
            _client_payload('git commit -m "x"', ["runtime/api/foo.py"])
        )
        assert reason is not None
        assert "runtime/api/foo.py" in reason

    def test_client_facts_stale_strategy_denies_under_no_main_check(
        self, tmp_db: str,
    ) -> None:
        reason = lint.evaluate_payload(
            _client_payload(
                'git commit -m "x"  # lint:no-main-check',
                [MISSION_REL],
                strategy_blobs=[_client_strategy_fact(MISSION_REL, EDITED_MISSION)],
            )
        )
        assert reason is not None
        assert "stale strategy rendered view" in reason

    def test_client_facts_fresh_strategy_authorizes(
        self, tmp_db: str,
    ) -> None:
        reason = lint.evaluate_payload(
            _client_payload(
                'git commit -m "x"',
                [MISSION_REL],
                strategy_blobs=[_client_strategy_fact(MISSION_REL, FRESH_MISSION)],
            )
        )
        assert reason is None

    def test_stale_view_denied_even_under_no_main_check(
        self, commit_world,
    ) -> None:
        commit_world.staged.append(MISSION_REL)
        commit_world.blobs[MISSION_REL] = EDITED_MISSION
        reason = lint.evaluate_payload(
            _payload('git commit -m "x"  # lint:no-main-check')
        )
        assert reason is not None
        assert "stale strategy rendered view" in reason
        assert "yoke strategy ingest" in reason
        # Recovery teaches the one-shot --commit path and warns off the
        # pipe-into-commit-chain trap that masks ingest's exit.
        assert "--commit" in reason
        assert "do NOT pipe ingest into the commit chain" in reason

    def test_mixed_commit_still_denied_per_file(self, commit_world) -> None:
        commit_world.staged.extend([MISSION_REL, "runtime/api/foo.py"])
        commit_world.blobs[MISSION_REL] = EDITED_MISSION
        with mock.patch.object(lint, "_active_worktree_items", lambda: []):
            reason = lint.evaluate_payload(_payload('git commit -m "x"'))
        # Zero in-flight worktree items would let the impl-on-main rule
        # pass — the freshness rule denies independently.
        assert reason is not None
        assert "MISSION" in reason

    def test_fresh_views_pass_through(self, commit_world) -> None:
        commit_world.staged.append(MISSION_REL)
        commit_world.blobs[MISSION_REL] = FRESH_MISSION
        reason = lint.evaluate_payload(_payload('git commit -m "x"'))
        assert reason is None  # matches-the-master authorizes the commit

    def test_own_token_suppresses_freshness_only(self, commit_world) -> None:
        commit_world.staged.append(MISSION_REL)
        commit_world.blobs[MISSION_REL] = EDITED_MISSION
        with mock.patch.object(lint, "_active_worktree_items", lambda: []):
            reason = lint.evaluate_payload(
                _payload(
                    'git commit -m "x"  # lint:no-strategy-freshness-check'
                )
            )
        assert reason is None

    def test_fail_closed_when_rows_unreadable(
        self, commit_world, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        commit_world.staged.append(MISSION_REL)
        commit_world.blobs[MISSION_REL] = FRESH_MISSION
        monkeypatch.setattr(
            claims_helper, "_commit_repo_project_context", lambda: None,
        )
        reason = lint.evaluate_payload(_payload('git commit -m "x"'))
        assert reason is not None
        assert "failing closed" in reason

    def test_non_strategy_commit_never_blocked_by_this_rule(
        self, commit_world, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        commit_world.staged.append("docs/lifecycle.md")
        monkeypatch.setattr(
            claims_helper, "_commit_repo_project_context", lambda: None,
        )
        with mock.patch.object(lint, "_active_worktree_items", lambda: []):
            reason = lint.evaluate_payload(_payload('git commit -m "x"'))
        assert reason is None


class TestMergeGate:
    def _ctx(self, tmp_path: Path):
        return SimpleNamespace(
            args=SimpleNamespace(target="main"),
            worktree_path=str(tmp_path),
            repo_root=str(tmp_path / "unmapped-main"),
            project=None,
        )

    def _mw(self, diff_paths, blobs):
        def _run_git(args, cwd=None, capture=False):
            if args[0] == "diff":
                return SimpleNamespace(
                    returncode=0, stdout="\n".join(diff_paths) + "\n",
                )
            if args[0] == "show":
                path = args[1].split(":", 1)[1]
                if path in blobs:
                    return SimpleNamespace(returncode=0, stdout=blobs[path])
                return SimpleNamespace(returncode=1, stdout="")
            raise AssertionError(f"unexpected git call: {args}")

        return SimpleNamespace(_run_git=_run_git)

    def test_no_strategy_changes_passes(self, tmp_db, tmp_path) -> None:
        from yoke_core.engines.merge_worktree_prepare_preflight import (
            _strategy_view_drift_check,
        )

        result = _strategy_view_drift_check(
            self._ctx(tmp_path), self._mw([], {}),
        )
        assert result is None

    def test_incoming_drift_refused_with_ingest_teaching(
        self, tmp_db, tmp_path, monkeypatch,
    ) -> None:
        from yoke_core.engines import merge_worktree_prepare_preflight as pf

        monkeypatch.setattr(pf, "_merge_project_id", lambda ctx: PROJECT_A)
        result = pf._strategy_view_drift_check(
            self._ctx(tmp_path),
            self._mw([MISSION_REL], {MISSION_REL: EDITED_MISSION}),
        )
        assert result is not None
        assert "strategy rendered-view drift" in result
        assert "yoke strategy ingest" in result

    def test_fresh_incoming_view_passes(
        self, tmp_db, tmp_path, monkeypatch,
    ) -> None:
        from yoke_core.engines import merge_worktree_prepare_preflight as pf

        monkeypatch.setattr(pf, "_merge_project_id", lambda ctx: PROJECT_A)
        result = pf._strategy_view_drift_check(
            self._ctx(tmp_path),
            self._mw([MISSION_REL], {MISSION_REL: FRESH_MISSION}),
        )
        assert result is None

    def test_rows_unreadable_fails_closed_only_with_changes(
        self, tmp_db, tmp_path, monkeypatch,
    ) -> None:
        from yoke_core.engines import merge_worktree_prepare_preflight as pf

        monkeypatch.setattr(pf, "_merge_project_id", lambda ctx: None)
        blocked = pf._strategy_view_drift_check(
            self._ctx(tmp_path),
            self._mw([MISSION_REL], {MISSION_REL: FRESH_MISSION}),
        )
        assert blocked is not None and "failing closed" in blocked
        clear = pf._strategy_view_drift_check(
            self._ctx(tmp_path), self._mw([], {}),
        )
        assert clear is None


class TestFindingClassification:
    def test_missing_row_and_sha_and_stale_header(self, tmp_db) -> None:
        rows = {"MISSION": (SEED_UPDATED_AT, SEED_CONTENT["MISSION"])}
        assert freshness.blob_freshness_finding(rows, "MISSION", FRESH_MISSION) is None
        assert "no strategy_docs row" in freshness.blob_freshness_finding(
            rows, "ROGUE", render_file_text("ROGUE", SEED_UPDATED_AT, "x\n"),
        )
        stale_header = render_file_text(
            "MISSION", "2026-06-09T00:00:00Z", SEED_CONTENT["MISSION"],
        )
        assert "stale render" in freshness.blob_freshness_finding(
            rows, "MISSION", stale_header,
        )
        assert "edited without write-back" in freshness.blob_freshness_finding(
            rows, "MISSION", EDITED_MISSION,
        )
        assert "header missing" in freshness.blob_freshness_finding(
            rows, "MISSION", "# MISSION\n\nno header\n",
        )
