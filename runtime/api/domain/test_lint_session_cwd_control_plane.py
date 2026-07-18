"""Regression coverage for the Yoke-control-plane carve-out and
PYTHONPATH equivalence in the session-cwd lint family.

Covers ACs 11-14 of YOK-1737:

* AC-11 — Yoke control-plane reads allowed for any active Yoke
  session regardless of held project-side claim; sibling-branch
  worktrees remain claim-gated.
* AC-12 — ``PYTHONPATH=<yoke-root>`` invocations are cwd-equivalent
  for Yoke-internal modules.
* AC-13 — End-to-end scenario: a session holding a project-side
  ``work_claim`` can run Yoke control-plane reads and Yoke module
  invocations from any cwd.
* AC-14 — ``BLOCKED`` message no longer mislabels a project repo as
  ``Control plane`` for a cross-project Yoke session.

AC-48 (``db_helpers.resolve_db_path`` PYTHONPATH heuristic) lives in
its sibling :mod:`test_db_helpers_pythonpath`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    project_id,
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import (
    lint_session_cwd,
    lint_session_cwd_control_plane,
    lint_session_cwd_validate,
)


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def fake_yoke_root(monkeypatch):
    """Pin the helper to a fake Yoke main repo path.

    The path is intentionally outside ``/tmp`` and ``/var/folders`` so
    the free-path allowlist cannot mask the carve-out logic this module
    is meant to exercise.
    """
    yoke_root = Path("/__yoke_test_root__")

    monkeypatch.setattr(
        lint_session_cwd_control_plane,
        "yoke_main_root",
        lambda: str(yoke_root),
    )
    # Keep ``/tmp`` free (production semantics — operators live there)
    # but drop ``/var/folders`` so pytest's ``tmp_path`` fixtures stop
    # incidentally short-circuiting the carve-out logic via the
    # free-path allowlist.
    monkeypatch.setattr(
        lint_session_cwd_validate,
        "FREE_PATH_PREFIXES",
        ("/tmp", "/private/tmp", "/dev"),
    )
    return yoke_root


@pytest.fixture
def cross_project_repo():
    return Path("/__externalwebapp_test_repo__")


def _seed_claimed_checkout(conn, repo_path, project="externalwebapp"):
    register_machine_checkout(
        Path(tempfile.mkdtemp(prefix="yoke-machine-config-")),
        Path(repo_path),
        project_id(project),
        create_checkout=False,
    )
    seed_item(conn, item_id=42, branch="YOK-42", project=project)
    seed_item_claim(conn, "sid-cross", item_id=42)


@pytest.fixture
def cross_project_session(conn, fake_yoke_root, cross_project_repo):
    """A Yoke session holding an active ExternalWebapp cross-project claim.

    Returns ``(fake_yoke_root, cross_project_repo)`` so individual
    tests can reference both roots without re-seeding the DB.
    """
    _seed_claimed_checkout(conn, cross_project_repo, project="externalwebapp")
    return fake_yoke_root, cross_project_repo


# ---------------------------------------------------------------------------
# AC-11 — Yoke control-plane reads carved out for any active session
# ---------------------------------------------------------------------------


class TestYokeControlPlaneCarveOut:
    def test_cross_project_session_may_read_yoke_runtime(
        self, cross_project_session,
    ):
        fake_yoke_root, _ = cross_project_session
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-cross",
            "tool_input": {
                "file_path": str(fake_yoke_root / "runtime" / "api"),
            },
        })
        assert verdict.allow is True

    def test_cross_project_session_may_test_dir_in_yoke(
        self, cross_project_session,
    ):
        fake_yoke_root, _ = cross_project_session
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-cross",
            "tool_input": {
                "command": f"test -d {fake_yoke_root}/.worktrees/YOK-42",
            },
        })
        # Sibling-branch worktree remains claim-gated.
        assert verdict.allow is False
        assert ".worktrees/YOK-42" in verdict.offending_target

    def test_yoke_data_dir_is_authorized(self, cross_project_session):
        fake_yoke_root, _ = cross_project_session

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-cross",
            "tool_input": {
                "file_path": str(fake_yoke_root / "data" / "config"),
            },
        })
        assert verdict.allow is True

    def test_sibling_branch_worktree_remains_claim_gated(
        self, cross_project_session,
    ):
        fake_yoke_root, _ = cross_project_session
        sibling = fake_yoke_root / ".worktrees" / "YOK-other" / "runtime"
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-cross",
            "tool_input": {"file_path": str(sibling)},
        })
        assert verdict.allow is False


# ---------------------------------------------------------------------------
# AC-12 — PYTHONPATH equivalence for Yoke-internal Python invocations
# ---------------------------------------------------------------------------


class TestPythonPathEquivalence:
    def test_module_invocation_from_foreign_cwd_authorized(
        self, cross_project_session,
    ):
        fake_yoke_root, _ = cross_project_session
        foreign_cwd = Path("/__foreign_cwd__")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-cross",
            "cwd": str(foreign_cwd),
            "tool_input": {
                "command": (
                    f"PYTHONPATH={fake_yoke_root} python3 -m "
                    f"yoke_core.cli.db_router items get YOK-42 status"
                ),
            },
        })
        assert verdict.allow is True

    def test_cd_to_tmp_prefix_still_authorized(self, cross_project_session):
        fake_yoke_root, _ = cross_project_session
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-cross",
            "cwd": "/tmp",
            "tool_input": {
                "command": (
                    f"cd /tmp && PYTHONPATH={fake_yoke_root} python3 -m "
                    f"yoke_core.cli.db_router items get YOK-42 status"
                ),
            },
        })
        assert verdict.allow is True

    def test_pythonpath_with_non_runtime_module_not_overridden(
        self, cross_project_session,
    ):
        fake_yoke_root, _ = cross_project_session
        foreign_cwd = Path("/__foreign_cwd__")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-cross",
            "cwd": str(foreign_cwd),
            "tool_input": {
                "command": (
                    f"PYTHONPATH={fake_yoke_root} python3 -m pip install foo"
                ),
            },
        })
        # `pip` is not a Yoke-internal module, so the override does
        # not apply and the foreign cwd is rejected.
        assert verdict.allow is False

    def test_foreign_pythonpath_not_overridden(
        self, cross_project_session,
    ):
        foreign_cwd = Path("/__foreign_cwd__")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-cross",
            "cwd": str(foreign_cwd),
            "tool_input": {
                "command": (
                    "PYTHONPATH=/not/yoke python3 -m "
                    "yoke_core.cli.db_router items get YOK-42 status"
                ),
            },
        })
        assert verdict.allow is False

    def test_override_skips_optional_cd_prefix(self, fake_yoke_root):
        cmd = (
            f"cd /tmp && PYTHONPATH={fake_yoke_root} python3 -m "
            f"yoke_core.cli.db_router items get YOK-42 status"
        )
        override = (
            lint_session_cwd_control_plane
            .extract_pythonpath_yoke_cwd_override(cmd)
        )
        assert override == str(fake_yoke_root)


# ---------------------------------------------------------------------------
# AC-14 — BLOCKED message wording
# ---------------------------------------------------------------------------


class TestBlockedMessageWording:
    def test_cross_project_session_message_names_yoke_separately(
        self, cross_project_session,
    ):
        fake_yoke_root, cross_project_repo = cross_project_session
        foreign = Path("/__foreign_target__/file")

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-cross",
            "tool_input": {"file_path": str(foreign)},
        })
        assert verdict.allow is False
        assert "Project control plane:" in verdict.reason
        assert str(cross_project_repo) in verdict.reason
        assert "Yoke control plane:" in verdict.reason
        assert str(fake_yoke_root) in verdict.reason

    def test_yoke_only_session_message_does_not_duplicate(
        self, conn, fake_yoke_root,
    ):
        # When the claimed project IS the Yoke repo itself, the
        # allowed-targets block suppresses the duplicate Yoke line.
        # Seed a Yoke-only claim (project repo == Yoke main root).
        register_machine_checkout(
            Path(tempfile.mkdtemp(prefix="yoke-machine-config-")),
            fake_yoke_root,
            project_id("yoke"),
            create_checkout=False,
        )
        seed_item(conn, item_id=42, branch="YOK-42")
        seed_item_claim(conn, "sid-yoke", item_id=42)

        foreign = Path("/__foreign_target__/file")

        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-yoke",
            "tool_input": {"file_path": str(foreign)},
        })
        assert verdict.allow is False
        assert "Project control plane:" in verdict.reason
        # No second 'Yoke control plane' line when the project repo
        # already equals the Yoke main root.
        assert verdict.reason.count("control plane:") == 1
