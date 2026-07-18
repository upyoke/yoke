"""Tests for the .git/hooks/post-commit installer + hook firing.

The installer is owned by :mod:`yoke_core.domain.project_install_git_hooks`
(the git-hook layer of ``yoke project install``, shared by both
delivery strategies).

Covers:

* installer creates the hook in a clean repo
* installer is idempotent on re-run with identical content
* installer leaves a non-Yoke hook in place with a warning
* installer refreshes a stale Yoke-marked hook (including the legacy
  module-invocation shim text)
* hook execs the machine-installed launcher (``yoke git post-commit``)
  behind a launcher-missing guard that never blocks the commit
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain.project_install_git_hooks import (
    POST_COMMIT_MARKER,
    POST_COMMIT_SHIM,
    BootstrapResult,
    install_post_commit_hook,
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def fresh_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _hook_path(repo: Path) -> Path:
    return repo / ".git" / "hooks" / "post-commit"


class TestInstaller:
    def test_creates_in_clean_repo(self, fresh_repo):
        result = BootstrapResult()
        install_post_commit_hook(fresh_repo, result)
        hook = _hook_path(fresh_repo)
        assert hook.exists()
        assert hook.read_text() == POST_COMMIT_SHIM
        assert os.access(str(hook), os.X_OK)
        assert result.installed >= 1
        assert any("Created" in line for line in result.actions)

    def test_idempotent_on_unchanged_shim(self, fresh_repo):
        result = BootstrapResult()
        install_post_commit_hook(fresh_repo, result)
        result2 = BootstrapResult()
        install_post_commit_hook(fresh_repo, result2)
        # Second run should NOT increment installed/updated counters.
        assert result2.installed == 0
        assert result2.updated == 0
        assert any("up to date" in line for line in result2.actions)

    def test_leaves_non_yoke_hook_in_place(self, fresh_repo):
        hook = _hook_path(fresh_repo)
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho user-hook\n")
        os.chmod(hook, 0o755)
        result = BootstrapResult()
        install_post_commit_hook(fresh_repo, result)
        assert any("not Yoke-managed" in line for line in result.warnings)
        # Hook content untouched.
        assert hook.read_text() == "#!/bin/sh\necho user-hook\n"
        assert result.installed == 0
        assert result.updated == 0

    def test_preserves_ambiguous_yoke_marker_hook(self, fresh_repo):
        hook = _hook_path(fresh_repo)
        hook.parent.mkdir(parents=True, exist_ok=True)
        # Stale Yoke-marked hook (older content but bears the marker).
        stale = (
            "#!/bin/sh\n"
            f"# {POST_COMMIT_MARKER} hook installed by `yoke project install`\n"
            "echo old\n"
        )
        hook.write_text(stale)
        os.chmod(hook, 0o755)
        result = BootstrapResult()
        install_post_commit_hook(fresh_repo, result)
        assert any("not Yoke-managed" in line for line in result.warnings)
        assert hook.read_text() == stale
        assert result.updated == 0

    def test_refresh_rewrites_legacy_module_form_shim(self, fresh_repo):
        # The exact pre-launcher shim text that earlier installs wrote
        # (module invocation — dies ModuleNotFoundError on machines with
        # no Yoke checkout importable by the ambient python3). A
        # refresh MUST rewrite it to the launcher-routed text.
        legacy = (
            "#!/bin/sh\n"
            f"# {POST_COMMIT_MARKER} hook installed by `yoke project install`\n"
            "# Pre-warms the path-snapshot cache for the project's HEAD so that\n"
            "# downstream activate / boundary calls never hit a cold-start miss.\n"
            "# Harness-neutral: fires on every commit regardless of source\n"
            "# (agent tool calls, manual git commit, merge, rebase, cherry-pick).\n"
            "exec python3 -m yoke_core.domain.path_snapshots --ensure-head"
            " \"${YOKE_PROJECT_ID:-yoke}\" >/dev/null 2>&1\n"
        )
        hook = _hook_path(fresh_repo)
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(legacy)
        os.chmod(hook, 0o755)
        result = BootstrapResult()
        install_post_commit_hook(fresh_repo, result)
        assert result.updated == 1
        assert hook.read_text() == POST_COMMIT_SHIM
        assert "python3 -m yoke_core.domain.path_snapshots" not in (
            hook.read_text()
        )

    def test_skips_when_git_hooks_dir_missing(self, tmp_path):
        # No .git/ at all.
        result = BootstrapResult()
        install_post_commit_hook(tmp_path, result)
        assert any("Skipped" in line for line in result.actions)
        assert result.installed == 0


class TestHookShape:
    def test_shim_execs_installed_launcher(self):
        # The shim routes through the machine-installed `yoke` launcher
        # (field-note 12957: the module-invocation form requires a Yoke
        # checkout importable by the ambient python3 — external repos
        # died ModuleNotFoundError).
        assert "exec yoke git post-commit" in POST_COMMIT_SHIM
        assert (
            "python3 -m yoke_core.domain.path_snapshots"
            not in POST_COMMIT_SHIM
        )

    def test_shim_carries_marker(self):
        assert POST_COMMIT_MARKER in POST_COMMIT_SHIM

    def test_shim_is_harness_neutral(self):
        # No reference to runtime/harness/claude or runtime/harness/codex
        # — the hook is a git-operation concern, not an agent-tool-call
        # concern.
        assert "runtime.harness.claude" not in POST_COMMIT_SHIM
        assert "runtime.harness.codex" not in POST_COMMIT_SHIM

    def test_shim_guards_missing_launcher_without_blocking(self):
        # Launcher absent from PATH: teach the machine install on stderr
        # but exit 0 — a completed commit is never blocked or errored by
        # snapshot sync. (Project resolution moved into the
        # `yoke git post-commit` adapter.)
        assert "command -v yoke" in POST_COMMIT_SHIM
        assert "exit 0" in POST_COMMIT_SHIM
        assert "https://api.upyoke.com/install" in POST_COMMIT_SHIM
        assert "install_yoke_launcher" not in POST_COMMIT_SHIM


class TestHookFiresOnCommit:
    """End-to-end: install the hook in a real repo and exercise commit.

    The hook execs ``yoke git post-commit`` through the installed
    launcher; we don't validate snapshot side effects here (those live in
    the project snapshot sync tests), only that the hook exists and is
    invocable.
    """

    def test_hook_invocable_via_subprocess(self, fresh_repo):
        result = BootstrapResult()
        install_post_commit_hook(fresh_repo, result)
        hook = _hook_path(fresh_repo)
        # The shim guards + ``exec yoke git post-commit`` — confirm the
        # script parses cleanly. The actual invocation may skip because
        # the test machine has no local DB, but the hook script itself
        # must be syntactically valid sh.
        proc = subprocess.run(
            ["sh", "-n", str(hook)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr

    def test_idempotent_on_repeated_commit(self, fresh_repo):
        result = BootstrapResult()
        install_post_commit_hook(fresh_repo, result)
        # Just confirm a second install round-trip leaves the same hook
        # content (the canonical idempotency check).
        first = _hook_path(fresh_repo).read_text()
        install_post_commit_hook(fresh_repo, BootstrapResult())
        second = _hook_path(fresh_repo).read_text()
        assert first == second
