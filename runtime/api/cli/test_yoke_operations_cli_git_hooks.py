"""Tests for the tool-shaped ``yoke git pre-commit`` / ``git post-commit``.

Field-note 12957: the installed ``.git/hooks`` shims exec these launcher
subcommands so hooked commits work in external repos with no Yoke
checkout importable by the ambient python3. Covers:

* CLI token routing (registry miss -> tool-shaped resolution; unknown
  tokens still exit 2)
* ``git pre-commit`` runs the harness-owned local gate (pass + file-line block)
* ``git post-commit`` delegates to
  ``yoke project snapshot sync --hook --head-only`` and exits 0 even
  when sync needs repair — never errors a completed commit
* operation-inventory rows (status=permanent, tool_shaped)
* shim text <-> routed tokens coupling, and refresh rewriting the
  legacy module-form pre-commit shim
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from yoke_cli.commands import git_hook as mod
from yoke_cli.main import main as cli_main
from yoke_core.domain.project_install_git_hooks import (
    PRE_COMMIT_MARKER,
    PRE_COMMIT_SHIM,
    POST_COMMIT_SHIM,
    BootstrapResult,
    install_pre_commit_hook,
)

_GATE_RUN = "yoke_harness.git_hooks.pre_commit.run"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )


@pytest.fixture
def scratch_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


class TestTokenRouting:
    def test_pre_commit_routes_to_gate_and_propagates_rc(self, monkeypatch):
        monkeypatch.setattr(_GATE_RUN, lambda: 7)
        assert cli_main(["git", "pre-commit"]) == 7

    def test_post_commit_routes(self, monkeypatch):
        monkeypatch.setattr(mod, "project_snapshot_sync", lambda _args: 0)
        assert cli_main(["git", "post-commit"]) == 0

    def test_unknown_git_token_exits_two(self, capsys):
        rc = cli_main(["git", "frobnicate"])
        assert rc == 2
        assert "unknown subcommand" in capsys.readouterr().err

    def test_bare_git_token_exits_two(self, capsys):
        rc = cli_main(["git"])
        assert rc == 2
        assert "unknown subcommand" in capsys.readouterr().err

    def test_help_lists_tool_shaped_commands(self, capsys):
        assert cli_main(["--help"]) == 0
        out = capsys.readouterr().out
        assert "yoke git pre-commit" in out
        assert "yoke git post-commit" in out

    def test_subcommand_help_does_not_run_gate(self, monkeypatch, capsys):
        def _boom() -> int:
            raise AssertionError("--help must not run the gate")

        monkeypatch.setattr(_GATE_RUN, _boom)
        assert cli_main(["git", "pre-commit", "--help"]) == 0
        assert "pre-commit gate" in capsys.readouterr().out.lower()

    def test_post_commit_help_names_snapshot_sync(self, capsys):
        assert cli_main(["git", "post-commit", "--help"]) == 0
        out = capsys.readouterr().out
        assert "yoke project snapshot sync --hook --head-only" in out


class TestPreCommitGateExecution:
    """The routed token executes the real gate logic (local-only)."""

    def test_clean_staged_change_passes(self, scratch_repo, monkeypatch):
        monkeypatch.chdir(scratch_repo)
        (scratch_repo / "ok.txt").write_text("one line\n")
        _git(scratch_repo, "add", "ok.txt")
        assert cli_main(["git", "pre-commit"]) == 0

    def test_oversize_authored_file_blocks(
        self, scratch_repo, monkeypatch, capsys,
    ):
        monkeypatch.chdir(scratch_repo)
        big = "\n".join(f"x = {i}" for i in range(400)) + "\n"
        (scratch_repo / "big.py").write_text(big)
        _git(scratch_repo, "add", "big.py")
        assert cli_main(["git", "pre-commit"]) == 1
        err = capsys.readouterr().err
        assert "file-line-limit gate blocked this commit" in err
        assert "big.py" in err


class TestPostCommitSnapshotSync:
    def test_delegates_to_snapshot_sync_hook_mode(self, monkeypatch, capsys):
        calls = []

        def fake_sync(args):
            calls.append(args)
            return 0

        monkeypatch.setattr(mod, "project_snapshot_sync", fake_sync)
        monkeypatch.delenv(mod.PROJECT_ID_ENV, raising=False)
        rc = cli_main(["git", "post-commit"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert calls == [["--hook", "--head-only"]]

    def test_legacy_project_env_passes_project_flag(self, monkeypatch, capsys):
        calls = []

        def fake_sync(args):
            calls.append(args)
            return 0

        monkeypatch.setattr(mod, "project_snapshot_sync", fake_sync)
        monkeypatch.setenv(mod.PROJECT_ID_ENV, "buzz")
        rc = cli_main(["git", "post-commit"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert calls == [["--hook", "--head-only", "--project", "buzz"]]

    def test_nonzero_snapshot_sync_still_exits_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "project_snapshot_sync", lambda _args: 7)
        rc = cli_main(["git", "post-commit"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "snapshot sync skipped" in err
        assert "yoke project snapshot sync --hook --head-only" in err

    def test_snapshot_sync_exception_still_exits_zero(self, monkeypatch, capsys):
        def fake_sync(_args):
            raise RuntimeError("transport offline")

        monkeypatch.setattr(mod, "project_snapshot_sync", fake_sync)
        assert cli_main(["git", "post-commit"]) == 0
        err = capsys.readouterr().err
        assert "snapshot sync skipped" in err
        assert "transport offline" in err


class TestOperationInventory:
    def test_rows_are_permanent_tool_shaped(self):
        from yoke_cli import operation_inventory as inv

        for shell_form in ("yoke git pre-commit", "yoke git post-commit"):
            entry = inv.lookup(shell_form)
            assert entry is not None, f"{shell_form!r} missing from inventory"
            assert entry.status == inv.PERMANENT
            assert entry.reason == inv.REASON_TOOL_SHAPED


class TestShimCliCoupling:
    """The installed shim text and the routed CLI tokens move together."""

    def test_shims_exec_the_routed_tokens(self):
        assert "exec yoke git pre-commit" in PRE_COMMIT_SHIM
        assert "exec yoke git post-commit" in POST_COMMIT_SHIM

    def test_shims_guard_missing_launcher(self):
        # Pre-commit fails CLOSED with teaching (a guardrail that
        # silently allows when the CLI is missing is not a guardrail);
        # post-commit teaches but exits 0 (commit already completed).
        assert PRE_COMMIT_SHIM.count("command -v yoke") == 1
        assert "exit 1" in PRE_COMMIT_SHIM
        assert "https://api.upyoke.com/install" in PRE_COMMIT_SHIM
        assert "machine-installed `yoke` launcher" in PRE_COMMIT_SHIM
        assert "editable install" in PRE_COMMIT_SHIM
        assert POST_COMMIT_SHIM.count("command -v yoke") == 1
        assert "exit 0" in POST_COMMIT_SHIM

    def test_no_module_invocation_form_remains(self):
        for shim in (PRE_COMMIT_SHIM, POST_COMMIT_SHIM):
            assert "python3 -m yoke_core.domain.git_pre_commit" not in shim
            assert (
                "python3 -m yoke_core.domain.path_snapshots" not in shim
            )

    def test_refresh_rewrites_legacy_module_form_pre_commit(
        self, scratch_repo,
    ):
        # The exact pre-launcher shim earlier installs wrote (the text
        # Buzz received before this slice) MUST be rewritten on refresh.
        legacy = (
            "#!/bin/sh\n"
            f"# {PRE_COMMIT_MARKER} hook installed by `yoke project install`\n"
            "# Hard-fails on file_line_check violations. "
            "Bypass with `git commit --no-verify`.\n"
            "exec python3 -m yoke_core.domain.git_pre_commit \"$@\"\n"
        )
        hook = scratch_repo / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(legacy)
        os.chmod(hook, 0o755)
        result = BootstrapResult()
        install_pre_commit_hook(scratch_repo, result)
        assert result.updated == 1
        assert hook.read_text() == PRE_COMMIT_SHIM
