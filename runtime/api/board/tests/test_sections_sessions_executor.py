"""Executor display rendering — surface alias preferred, canonical fallback.

Companion to ``test_sections_sessions.py``; the render database it seeds
lives in ``sessions_render_test_support``.
"""

from __future__ import annotations

from pathlib import Path

from runtime.api.board.tests.sessions_render_test_support import (
    insert_render_item_claim,
    insert_render_session,
    make_render_db,
)


class TestExecutorDisplayRendering:
    """Board prefers ``executor_surface`` and falls back to ``executor``."""

    def test_display_alias_preferred_when_present(self, tmp_path: Path) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="surface-claude",
                executor="claude-code",
                executor_surface="claude-desktop",
            )
            section = render(db)
        assert "claude-desktop" in section
        # canonical id not shown standalone when the alias is present
        assert "claude-code" not in section

    def test_cursor_card_renders_the_stored_model_verbatim(
        self, tmp_path: Path
    ) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="cursor-cli-sess",
                executor="cursor",
                executor_surface="cursor-cli",
                model="cursor-grok-4.6-xhigh",
            )
            section = render(db)
        assert "cursor-grok-4.6-xhigh" in section

    def test_canonical_used_when_display_alias_absent(self, tmp_path: Path) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db, session_id="coarse-codex", executor="codex", executor_surface=None
            )
            section = render(db)
        assert "codex" in section

    def test_closed_session_also_prefers_display_alias(self, tmp_path: Path) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="ended-codex",
                executor="codex",
                executor_surface="codex-vscode",
                ended_at="2026-05-19T20:30:00Z",
            )
            section = render(db)
        assert "codex-vscode" in section

    def test_project_scope_filters_active_sessions(self, tmp_path: Path) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="externalwebappsess",
                executor="codex",
                executor_surface="codex-vscode",
                project_id=2,
            )
            insert_render_session(
                db,
                session_id="yokesess",
                executor="codex",
                executor_surface="codex-desktop",
                project_id=1,
            )
            insert_render_item_claim(
                db,
                session_id="externalwebappsess",
                item_id=10,
                project="externalwebapp",
            )
            insert_render_item_claim(
                db, session_id="yokesess", item_id=11, project="yoke"
            )
            section = render(db, scope="externalwebapp")
        assert "externalwebappsess" in section
        assert "yokesess" not in section

    def test_project_scope_uses_session_project_id_before_workspace(
        self, tmp_path: Path
    ) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="externalwebappdir",
                executor="codex",
                executor_surface="codex-desktop",
                workspace="/some/other/machine/externalwebapp",
                project_id=2,
            )
            insert_render_session(
                db,
                session_id="yokedir",
                executor="codex",
                executor_surface="codex-desktop",
                workspace="/tmp/externalwebapp",
                project_id=1,
            )
            section = render(db, scope="externalwebapp")
        assert "externalwebappdir" in section
        assert "yokedir" not in section

    def test_project_scope_uses_stamped_client_checkout_identity(
        self, tmp_path: Path
    ) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="mac-externalwebapp",
                executor="claude-code",
                executor_surface="claude-desktop",
                workspace="/Users/testy/code/externalwebapp",
                project_id=2,
            )
            section = render(db, scope="externalwebapp")
        assert "mac-externalwebapp" in section
        assert "🧩 externalwebapp" in section

    def test_project_scope_excludes_other_project_even_when_workspace_matches_repo_path(
        self, tmp_path: Path
    ) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="mac-externalwebapp",
                executor="claude-code",
                executor_surface="claude-desktop",
                workspace="/Users/testy/code/externalwebapp",
                project_id=1,
            )
            section = render(db, scope="externalwebapp")
        assert "mac-externalwebapp" not in section

    def test_active_session_renders_workspace_project_column(
        self, tmp_path: Path
    ) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="externalwebappdir",
                executor="codex",
                executor_surface="codex-desktop",
                workspace="/tmp/externalwebapp/app",
                project_id=2,
            )
            section = render(db, scope="externalwebapp")
        assert "| Project" in section
        assert "| Executor" in section
        assert "🧩 externalwebapp" in section

    def test_closed_session_renders_workspace_project_column(
        self, tmp_path: Path
    ) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="yokedir",
                executor="claude-code",
                executor_surface="claude-desktop",
                execution_level="ALTMAN",
                workspace="/tmp/yoke",
                project_id=1,
                ended_at="2026-05-19T20:30:00Z",
            )
            section = render(db, scope="yoke")
        assert "Recent Harness Sessions" in section
        assert "Project" in section
        assert "Level" in section
        assert "👓 ALTMAN" in section
        assert "🐂 yoke" in section

    def test_claim_scope_can_include_an_active_session_from_another_checkout(
        self, tmp_path: Path
    ) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="known-yoke",
                executor="codex",
                workspace="/tmp/yoke",
                project_id=1,
            )
            insert_render_item_claim(
                db, session_id="known-yoke", item_id=12, project="externalwebapp"
            )
            section = render(db, scope="externalwebapp")
        assert "known-yoke" in section
        assert "🐂 yoke" in section

    def test_project_identity_does_not_fall_back_to_workspace_path(
        self, tmp_path: Path
    ) -> None:
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="externalwebapp-path-yoke-project",
                executor="codex",
                workspace="/tmp/externalwebapp",
                project_id=1,
            )
            section = render(db, scope="externalwebapp")
        assert "externalwebapp-path-yoke-project" not in section

    def test_a_killed_session_is_ended_even_without_an_ordinary_end_stamp(
        self, tmp_path: Path
    ) -> None:
        """The two end stamps are independent; either one means gone.

        A session terminated without an ordinary wind-down carries only
        ``terminated_at``. Splitting the board on ``ended_at`` alone left it
        under the live table indefinitely, while the control plane had already
        classified it ended.
        """
        with make_render_db(tmp_path) as (db, render):
            insert_render_session(
                db,
                session_id="killedsess",
                executor="codex",
                workspace="/tmp/yoke",
                project_id=1,
                terminated_at="2026-05-19T20:30:00Z",
            )
            section = render(db, scope="yoke")
        live, _, ended = section.partition("Recent Harness Sessions")
        assert "killedsess" in ended
        assert "killedsess" not in live
        # The kill stamp also dates the row: an undated end renders "?" and
        # leaves the duration uncomputable, so both cells prove the fallback.
        row = ended.split("killedsess", 1)[1].split("\n", 1)[0]
        assert "? ago" not in row
        assert "30m" in row
