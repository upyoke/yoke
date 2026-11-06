"""External scratch and harness paths need no repository claim."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_session_cwd_path_authority
from yoke_core.domain.lint_session_cwd_path_authority import (
    free_path_prefixes, is_yoke_watcher_capture_path,
)
from yoke_core.domain.lint_session_cwd_validate import (
    validate_targets,
)
from yoke_core.domain.project_scratch_dir import (
    dispatch_inputs_dir,
    mint_watcher_capture_pair,
)

pytestmark = pytest.mark.usefixtures("bound_project_context")

#: A home outside every OS temp root, like a real machine's. The isolated
#: per-test HOME lives under the temp root, which is itself a free path, so
#: refusals of home paths could never be observed there. Nothing is written
#: under it: ``/`` is not writable, so a stray write fails loudly.
NON_TEMP_HOME = "/__yoke_test_home__"


@pytest.fixture(autouse=True)
def _home_outside_temp_roots(monkeypatch):
    monkeypatch.setenv("HOME", NON_TEMP_HOME)


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def session_with_claim(conn, tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees" / "YOK-100").mkdir(parents=True)
    register_machine_checkout(tmp_path / "machine-config", repo_path, 1)
    seed_item(conn, item_id=100, branch="YOK-100", repo_path=repo_path)
    seed_item_claim(conn, "s1", item_id=100)
    return "s1"


class TestFreePathPrefixesContainExpectedRoots:
    """Static check: the expansion landed and the literal forms are present."""

    def test_dev_family_in_free_paths(self) -> None:
        assert "/dev" in free_path_prefixes()

    def test_harness_internal_literal_form_in_free_paths(self) -> None:
        assert "~/.claude/projects" in free_path_prefixes()

    def test_harness_internal_expanded_form_in_free_paths(self) -> None:
        home = os.path.expanduser("~")
        expected = os.path.join(home, ".claude", "projects")
        assert expected in free_path_prefixes()

    def test_codex_sessions_literal_form_in_free_paths(self) -> None:
        assert "~/.codex/sessions" in free_path_prefixes()

    def test_codex_sessions_expanded_form_in_free_paths(self) -> None:
        home = os.path.expanduser("~")
        expected = os.path.join(home, ".codex", "sessions")
        assert expected in free_path_prefixes()

    def test_codex_archived_sessions_literal_form_in_free_paths(self) -> None:
        assert "~/.codex/archived_sessions" in free_path_prefixes()

    def test_codex_archived_sessions_expanded_form_in_free_paths(self) -> None:
        home = os.path.expanduser("~")
        expected = os.path.join(home, ".codex", "archived_sessions")
        assert expected in free_path_prefixes()


class TestDevFamilyAllowed:
    """``/dev/null`` and friends bypass claim authority."""

    @pytest.mark.parametrize(
        "target",
        [
            "/dev/null",
            "/dev/stderr",
            "/dev/stdout",
            "/dev/tty",
        ],
    )
    def test_dev_targets_allowed(self, conn, session_with_claim, target) -> None:
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow, (
            f"expected {target} to be allowed via /dev free-path prefix"
        )


class TestHarnessInternalAllowed:
    """``~/.claude/projects/<session>/...`` lands in tool-results / persisted-output."""

    def test_tool_results_literal_tilde_allowed(self, conn, session_with_claim) -> None:
        target = "~/.claude/projects/-Users-x-yoke/sess/tool-results/file.txt"
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_tool_results_expanded_allowed(self, conn, session_with_claim) -> None:
        home = os.path.expanduser("~")
        target = os.path.join(
            home,
            ".claude",
            "projects",
            "-Users-x-yoke",
            "sess",
            "tool-results",
            "file.txt",
        )
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_persisted_output_allowed(self, conn, session_with_claim) -> None:
        home = os.path.expanduser("~")
        target = os.path.join(
            home,
            ".claude",
            "projects",
            "-Users-x-yoke",
            "sess",
            "persisted-output",
            "capture.txt",
        )
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow


class TestCodexHarnessInternalAllowed:
    """``~/.codex/sessions/...`` and ``~/.codex/archived_sessions/...`` are symmetric to the Claude tree."""

    def test_codex_sessions_literal_tilde_allowed(
        self, conn, session_with_claim
    ) -> None:
        target = "~/.codex/sessions/2026/04/03/rollout-019d54b0.jsonl"
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_codex_sessions_expanded_allowed(self, conn, session_with_claim) -> None:
        home = os.path.expanduser("~")
        target = os.path.join(
            home,
            ".codex",
            "sessions",
            "2026",
            "04",
            "03",
            "rollout-019d54b0.jsonl",
        )
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_codex_archived_sessions_literal_tilde_allowed(
        self, conn, session_with_claim
    ) -> None:
        target = "~/.codex/archived_sessions/old-rollout.jsonl"
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow

    def test_codex_archived_sessions_expanded_allowed(
        self, conn, session_with_claim
    ) -> None:
        home = os.path.expanduser("~")
        target = os.path.join(
            home,
            ".codex",
            "archived_sessions",
            "old-rollout.jsonl",
        )
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[target],
        )
        assert verdict.allow


class TestWatcherMintedCapturePairAllowed:
    """Printed ``--print-streaming-pair`` paths must pass write authority."""

    def test_minted_pair_targets_allowed(
        self, conn, session_with_claim, monkeypatch, tmp_path
    ) -> None:
        # External scratch paths pass without a special allowlist.
        monkeypatch.delenv("TMPDIR", raising=False)
        monkeypatch.setattr(
            lint_session_cwd_path_authority, "_STATIC_FREE_PATH_PREFIXES", ()
        )
        scratch = tmp_path / "test-scratch-watcher-authority"
        scratch.mkdir()
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(scratch))
        monkeypatch.setenv("YOKE_SESSION_ID", session_with_claim)
        try:
            raw, progress = mint_watcher_capture_pair("pytest")
            assert str(raw).startswith(str(scratch.resolve()))
            assert is_yoke_watcher_capture_path(str(raw))
            for target in (str(raw), str(progress)):
                verdict = validate_targets(
                    conn,
                    session_id=session_with_claim,
                    targets=[target],
                )
                assert verdict.allow, (
                    f"expected minted watcher capture {target} to pass "
                    f"authority outside governed repositories"
                )
            dispatch_target = str(
                dispatch_inputs_dir(
                    public_ref="YOK-100",
                    session_id="s1",
                    attempt=1,
                    create=False,
                )
                / "prompt.md"
            )
            assert not is_yoke_watcher_capture_path(dispatch_target)
            denied = validate_targets(
                conn,
                session_id=session_with_claim,
                targets=[dispatch_target],
            )
            assert denied.allow
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


class TestClaudeJobTmpAllowed:
    """The current background-job harness temp subtree is claim-free."""

    def test_job_tmp_target_allowed(self, conn, session_with_claim) -> None:
        root = Path.home() / ".claude" / "jobs" / "job-123" / "tmp"
        target = root / "verification.log"

        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[str(target)],
        )

        assert verdict.allow

    def test_job_sibling_outside_repositories_allowed(self, conn, session_with_claim) -> None:
        job = Path.home() / ".claude" / "jobs" / "job-123"
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=[str(job / "result.json")],
        )

        assert verdict.allow


class TestNegativeRegression:
    """External paths do not need a repository claim."""

    def test_etc_passwd_outside_repositories_allowed(self, conn, session_with_claim) -> None:
        verdict = validate_targets(
            conn,
            session_id=session_with_claim,
            targets=["/etc/passwd"],
        )
        assert verdict.allow


@pytest.mark.parametrize("tmpdir", ["/run/user/1234/../5678", "relative/tmp", ""])
def test_absolute_tmpdir_is_canonical_and_shared_with_guard(
    conn,
    session_with_claim,
    monkeypatch,
    tmpdir,
):
    from yoke_contracts.free_paths import free_path_prefixes, is_under_free_path_prefix
    from yoke_core.domain.lint_session_cwd_path_authority import is_free_path

    monkeypatch.setenv("TMPDIR", tmpdir)
    accepted = bool(tmpdir and Path(tmpdir).is_absolute())
    root = Path(tmpdir).resolve() if accepted else Path("/__unconfigured_tmpdir__")
    target = root / "capture.log"
    assert (str(root) in free_path_prefixes()) is accepted
    assert (
        is_under_free_path_prefix(target, prefixes=free_path_prefixes()[-1:])
        is accepted
    )
    verdict = validate_targets(
        conn, session_id=session_with_claim, targets=[str(target)]
    )
    assert verdict.allow
    if accepted:
        assert is_free_path(str(target))
        assert not is_free_path(str(root) + "-sibling/capture.log")
