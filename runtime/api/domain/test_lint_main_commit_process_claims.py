"""Tests for ``lint_main_commit_process_claims``.

Focused on the two helpers wired into ``lint_main_commit.evaluate_payload``:

* :func:`is_actual_git_commit` -- the tokenizer-based replacement for the
  legacy ``"git commit" in command`` substring check. Quoted field-note
  evidence MUST NOT classify as a commit attempt.
* :func:`is_strategy_commit_authorized` -- the matches-the-master rule
  for strategy rendered-view commits on ``main``. Authorization requires
  every STAGED file to byte-match its live ``strategy_docs`` row (header
  parses, ``updated_at`` current, body hash equals the row content); no
  claim lookup happens at commit time.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yoke_core.domain import db_backend
from yoke_core.domain import lint_main_commit_process_claims as helper
from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.strategy_docs_header import render_file_text
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


class TestIsActualGitCommit(unittest.TestCase):
    def test_bare_commit_command(self) -> None:
        self.assertTrue(helper.is_actual_git_commit('git commit -m "msg"'))

    def test_commit_with_repo_path(self) -> None:
        self.assertTrue(
            helper.is_actual_git_commit('git -C /tmp/repo commit -m "msg"')
        )

    def test_commit_with_config_override(self) -> None:
        self.assertTrue(
            helper.is_actual_git_commit(
                'git -c user.name=Test commit -m "msg"'
            )
        )

    def test_commit_after_separator(self) -> None:
        self.assertTrue(
            helper.is_actual_git_commit('git add -A && git commit -m "msg"')
        )

    def test_commit_inside_double_quoted_argument(self) -> None:
        # The text "git commit" appears inside an --evidence argument as
        # field-note payload -- not a real commit attempt.
        cmd = (
            'yoke ouroboros field-note append --kind failed '
            '--evidence "git commit was blocked by lint-main-commit"'
        )
        self.assertFalse(helper.is_actual_git_commit(cmd))

    def test_commit_inside_single_quoted_argument(self) -> None:
        cmd = (
            "yoke ouroboros field-note append --kind unclear "
            "--evidence 'previous attempt: git commit refused'"
        )
        self.assertFalse(helper.is_actual_git_commit(cmd))

    def test_commit_inside_heredoc_like_payload(self) -> None:
        # printf with a quoted string that mentions the words is not an
        # actual commit invocation.
        cmd = "printf '%s\\n' 'tried git commit and got refused'"
        self.assertFalse(helper.is_actual_git_commit(cmd))

    def test_not_git_at_all(self) -> None:
        self.assertFalse(helper.is_actual_git_commit("ls -la"))

    def test_git_subcommand_other_than_commit(self) -> None:
        self.assertFalse(helper.is_actual_git_commit("git status"))
        self.assertFalse(helper.is_actual_git_commit('git log -1'))

    def test_empty_command(self) -> None:
        self.assertFalse(helper.is_actual_git_commit(""))

    def test_none_command(self) -> None:
        self.assertFalse(helper.is_actual_git_commit(None))  # type: ignore[arg-type]

    def test_unbalanced_quotes_falls_back_to_word_check(self) -> None:
        # Unbalanced quotes prevent shlex tokenization; the helper falls
        # back to the conservative whitespace check. ``git commit`` as
        # adjacent unquoted words is the positive shape there.
        self.assertTrue(
            helper.is_actual_git_commit('git commit -m "unclosed')
        )
        self.assertFalse(helper.is_actual_git_commit('"git commit'))


SEED_UPDATED_AT = "2026-06-10T00:00:00Z"

REPO_PROJECT_ID = 1
OTHER_PROJECT_ID = 2

_VIEW_DIR = ".yoke/strategy"


def _apply_strategy_schema() -> None:
    """Full production schema + the two fixture projects.

    The dispatcher-backed row loader resolves ``target.project_id``
    against the projects table and runs the full dispatch pipeline
    (identity binding, events), so the fixture provisions the real
    schema rather than a strategy_docs-only slice.
    """
    from yoke_core.domain import schema
    from yoke_core.domain.schema_init_apply import execute_schema_script

    schema.cmd_init()
    conn = db_backend.connect()
    try:
        execute_schema_script(
            conn,
            """
            INSERT INTO projects (id, slug, name, created_at)
              VALUES (1, 'alpha', 'Alpha', '2026-01-01T00:00:00Z')
              ON CONFLICT (id) DO NOTHING;
            INSERT INTO projects (id, slug, name, created_at)
              VALUES (2, 'beta', 'Beta', '2026-01-01T00:00:00Z')
              ON CONFLICT (id) DO NOTHING;
            """,
        )
        conn.commit()
    finally:
        conn.close()


class TestIsStrategyCommitAuthorized(unittest.TestCase):
    """Matches-the-master freshness rule against a real index.

    The repo's checkout→project mapping is patched at the helper seam
    (``_commit_repo_project_context``) — machine-config resolution has
    its own coverage and tests must not read the developer's real
    ``~/.yoke/config.json``.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_ctx = init_test_db(
            Path(self._tmpdir.name), apply_schema=_apply_strategy_schema
        )
        self.db_path = self._db_ctx.__enter__()
        self.repo = Path(self._tmpdir.name) / "repo"
        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(self.repo)], check=True, timeout=10,
        )
        (self.repo / _VIEW_DIR).mkdir(parents=True)
        self._old_cwd = os.getcwd()
        os.chdir(self.repo)
        self._project_patch = mock.patch.object(
            helper, "_commit_repo_project_context",
            return_value=str(REPO_PROJECT_ID),
        )
        self._project_patch.start()

    def tearDown(self) -> None:
        self._project_patch.stop()
        os.chdir(self._old_cwd)
        self._db_ctx.__exit__(None, None, None)
        self._tmpdir.cleanup()

    def _seed_row(
        self, slug: str, content: str, updated_at: str = SEED_UPDATED_AT,
        project_id: int = REPO_PROJECT_ID,
    ) -> None:
        conn = connect_test_db(self.db_path)
        try:
            conn.execute(
                f"INSERT INTO {sd.STRATEGY_DOCS_TABLE} "
                "(project_id, slug, content, updated_at) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (project_id, slug) DO UPDATE SET "
                "content = EXCLUDED.content, updated_at = EXCLUDED.updated_at",
                (project_id, slug, content, updated_at),
            )
            conn.commit()
        finally:
            conn.close()

    def _stage(self, slug: str, file_text: str) -> None:
        path = self.repo / _VIEW_DIR / f"{slug}.md"
        path.write_text(file_text, encoding="utf-8")
        subprocess.run(
            ["git", "add", "-f", f"{_VIEW_DIR}/{slug}.md"],
            check=True, cwd=self.repo, timeout=10,
        )

    def _stage_fresh(self, slug: str, content: str) -> None:
        self._seed_row(slug, content)
        self._stage(slug, render_file_text(slug, SEED_UPDATED_AT, content))

    def test_authorized_when_staged_files_are_fresh_renders(self) -> None:
        self._stage_fresh("MISSION", "# MISSION\n\nbody\n")
        self._stage_fresh("PAD", "# PAD\n\nideas\n")
        self.assertTrue(
            helper.is_strategy_commit_authorized(
                [f"{_VIEW_DIR}/MISSION.md", f"{_VIEW_DIR}/PAD.md"]
            )
        )

    def test_authorized_from_staged_blob_even_with_dirty_worktree(self) -> None:
        # The commit ships the index: a fresh STAGED copy authorizes even
        # when the working-tree file was scribbled on afterwards.
        self._stage_fresh("MISSION", "# MISSION\n\nbody\n")
        (self.repo / _VIEW_DIR / "MISSION.md").write_text(
            "scribbled over after staging\n", encoding="utf-8",
        )
        self.assertTrue(
            helper.is_strategy_commit_authorized([f"{_VIEW_DIR}/MISSION.md"])
        )

    def test_denied_when_staged_body_differs_from_db(self) -> None:
        self._seed_row("MISSION", "# MISSION\n\nbody\n")
        self._stage(
            "MISSION",
            render_file_text(
                "MISSION", SEED_UPDATED_AT, "# MISSION\n\nhand-edited\n"
            ),
        )
        self.assertFalse(
            helper.is_strategy_commit_authorized([f"{_VIEW_DIR}/MISSION.md"])
        )

    def test_denied_when_header_base_is_stale(self) -> None:
        content = "# MISSION\n\nbody\n"
        self._seed_row("MISSION", content, updated_at="2026-06-11T11:11:11Z")
        self._stage(
            "MISSION", render_file_text("MISSION", SEED_UPDATED_AT, content),
        )
        self.assertFalse(
            helper.is_strategy_commit_authorized([f"{_VIEW_DIR}/MISSION.md"])
        )

    def test_denied_when_header_missing(self) -> None:
        self._seed_row("MISSION", "# MISSION\n\nbody\n")
        self._stage("MISSION", "# MISSION\n\nbody\n")  # no header line
        self.assertFalse(
            helper.is_strategy_commit_authorized([f"{_VIEW_DIR}/MISSION.md"])
        )

    def test_denied_when_any_staged_file_outside_view_dir(self) -> None:
        self._stage_fresh("MISSION", "# MISSION\n\nbody\n")
        # Mixed commits fall through to the normal item-claim rules.
        self.assertFalse(
            helper.is_strategy_commit_authorized(
                [f"{_VIEW_DIR}/MISSION.md", "runtime/api/foo.py"]
            )
        )

    def test_denied_when_db_row_missing(self) -> None:
        self._stage(
            "MISSION",
            render_file_text(
                "MISSION", SEED_UPDATED_AT, "# MISSION\n\nbody\n"
            ),
        )
        self.assertFalse(
            helper.is_strategy_commit_authorized([f"{_VIEW_DIR}/MISSION.md"])
        )

    def test_denied_when_row_belongs_to_another_project(self) -> None:
        # The same slug fresh under ANOTHER project never authorizes this
        # checkout's commit — rows are per-project authority.
        content = "# MISSION\n\nbody\n"
        self._seed_row(
            "MISSION", content, project_id=OTHER_PROJECT_ID,
        )
        self._stage(
            "MISSION", render_file_text("MISSION", SEED_UPDATED_AT, content),
        )
        self.assertFalse(
            helper.is_strategy_commit_authorized([f"{_VIEW_DIR}/MISSION.md"])
        )

    def test_denied_when_checkout_unmapped(self) -> None:
        self._stage_fresh("MISSION", "# MISSION\n\nbody\n")
        with mock.patch.object(
            helper, "_commit_repo_project_context", return_value=None,
        ):
            self.assertFalse(
                helper.is_strategy_commit_authorized(
                    [f"{_VIEW_DIR}/MISSION.md"]
                )
            )

    def test_denied_with_empty_staged_set(self) -> None:
        self.assertFalse(helper.is_strategy_commit_authorized([]))


class TestDeniedWhenTableMissing(unittest.TestCase):
    """Pre-cutover (no strategy_docs table) nothing authorizes."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        # No apply_schema: the disposable DB has no strategy_docs table.
        self._db_ctx = init_test_db(Path(self._tmpdir.name), apply_schema=lambda: None)
        self.db_path = self._db_ctx.__enter__()
        self.repo = Path(self._tmpdir.name) / "repo"
        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(self.repo)], check=True, timeout=10,
        )
        (self.repo / _VIEW_DIR).mkdir(parents=True)
        self._old_cwd = os.getcwd()
        os.chdir(self.repo)
        self._project_patch = mock.patch.object(
            helper, "_commit_repo_project_context",
            return_value=str(REPO_PROJECT_ID),
        )
        self._project_patch.start()

    def tearDown(self) -> None:
        self._project_patch.stop()
        os.chdir(self._old_cwd)
        self._db_ctx.__exit__(None, None, None)
        self._tmpdir.cleanup()

    def test_denied_without_strategy_docs_table(self) -> None:
        path = self.repo / _VIEW_DIR / "MISSION.md"
        path.write_text(
            render_file_text(
                "MISSION", SEED_UPDATED_AT, "# MISSION\n\nbody\n"
            ),
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "-f", f"{_VIEW_DIR}/MISSION.md"],
            check=True, cwd=self.repo, timeout=10,
        )
        self.assertFalse(
            helper.is_strategy_commit_authorized([f"{_VIEW_DIR}/MISSION.md"])
        )


if __name__ == "__main__":
    unittest.main()
