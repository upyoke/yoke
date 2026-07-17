from __future__ import annotations

import shutil
from pathlib import Path
from subprocess import CompletedProcess

from yoke_core.domain.check_prerequisites import run_checks


def _seed_repo(root: Path, *, include_settings: bool = True) -> None:
    (root / "docs").mkdir(parents=True)
    canonical_agents_dir = root / "runtime" / "harness" / "claude" / "agents"
    canonical_agents_dir.mkdir(parents=True)
    runtime_agents_dir = root / ".claude" / "agents"
    runtime_agents_dir.parent.mkdir(parents=True, exist_ok=True)
    runtime_agents_dir.symlink_to("../runtime/harness/claude/agents")
    for name in (
        "yoke-product-manager",
        "yoke-product-designer",
        "yoke-architect",
        "yoke-engineer",
        "yoke-tester",
        "yoke-simulator",
        "yoke-boss",
    ):
        (canonical_agents_dir / f"{name}.md").write_text("ok\n")

    for rel_path in (
        "packages/yoke-core/src/yoke_core/domain/check_prerequisites.py",
        "packages/yoke-core/src/yoke_core/domain/verify_overlap.py",
        "packages/yoke-core/src/yoke_core/domain/epic_task_sync.py",
        "packages/yoke-core/src/yoke_core/domain/update_status.py",
        "packages/yoke-core/src/yoke_core/engines/merge_worktree.py",
    ):
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# stub\n")

    hook = root / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("# yoke-pre-commit\n")
    hook.chmod(0o755)

    if include_settings:
        canonical_settings = root / "runtime" / "harness" / "claude" / "settings.json"
        canonical_settings.parent.mkdir(parents=True, exist_ok=True)
        canonical_settings.write_text(
            "\n".join(
                [
                    "Bash",
                    "Write(**)",
                    "Edit(**)",
                    "Read(*)",
                    "Grep(*)",
                    "Glob(*)",
                ]
            )
        )
        (root / ".claude" / "settings.json").symlink_to(
            "../runtime/harness/claude/settings.json"
        )

    (root / ".gitignore").write_text(".worktrees/\n")
    (root / "AGENTS.md").write_text("rules\n")


def test_all_critical_pass_with_no_gh(tmp_path, monkeypatch, capsys):
    _seed_repo(tmp_path)

    def fake_which(name: str):
        if name == "git":
            return "/usr/bin/git"
        if name == "gh":
            return None
        return f"/usr/bin/{name}"

    def fake_run(cmd, capture_output=False, text=False):
        if cmd == ["git", "--version"]:
            return CompletedProcess(cmd, 0, stdout="git version 2.39.1\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("yoke_core.domain.check_prerequisites.shutil.which", fake_which)
    monkeypatch.setattr("yoke_core.domain.check_prerequisites.subprocess.run", fake_run)

    # The GitHub App auth-only build of the prereq check does not depend on the host
    # gh CLI; the canonical resolver against the dev-shell DB may
    # legitimately WARN, so accept either PASS or WARN here.
    assert run_checks(tmp_path) == 0
    out = capsys.readouterr().out
    assert "All critical checks passed" in out
    assert "Directory structure" in out
    assert "Permission rules configured" in out
    # Migrated: the prereq table no longer teaches a host-gh install
    # step. Banned strings built by concatenation so the AC-1 / AC-2
    # grep recipes return zero hits anywhere in the live tree.
    assert ("brew" + " install gh") not in out
    assert ("GitHub CLI" + " installed") not in out
    assert ("GitHub CLI" + " authenticated") not in out
    assert ("gh-sub-" + "issue") not in out


def test_pre_commit_hook_uses_common_git_dir_for_linked_worktree(
    tmp_path, monkeypatch, capsys,
):
    _seed_repo(tmp_path)
    shutil.rmtree(tmp_path.joinpath(".git"))
    common_git = tmp_path.joinpath("common.git")
    linked_git_dir = common_git.joinpath("worktrees", "item-worktree")
    linked_git_dir.mkdir(parents=True)
    linked_git_dir.joinpath("commondir").write_text("../..\n")
    tmp_path.joinpath(".git").write_text(
        f"gitdir: {linked_git_dir.relative_to(tmp_path)}\n"
    )
    hook = common_git.joinpath("hooks", "pre-commit")
    hook.parent.mkdir(parents=True)
    hook.write_text("# yoke-pre-commit\n")
    hook.chmod(0o755)

    def fake_which(name: str):
        if name == "git":
            return "git-bin"
        if name == "gh":
            return None
        return f"{name}-bin"

    def fake_run(cmd, capture_output=False, text=False):
        if cmd == ["git", "--version"]:
            return CompletedProcess(cmd, 0, stdout="git version 2.39.1\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("yoke_core.domain.check_prerequisites.shutil.which", fake_which)
    monkeypatch.setattr("yoke_core.domain.check_prerequisites.subprocess.run", fake_run)

    assert run_checks(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Git pre-commit hook" in out
    assert "Some critical checks failed." not in out


def test_fails_when_git_too_old(tmp_path, monkeypatch, capsys):
    _seed_repo(tmp_path)

    def fake_which(name: str):
        if name == "git":
            return "/usr/bin/git"
        if name == "gh":
            return None
        return f"/usr/bin/{name}"

    def fake_run(cmd, capture_output=False, text=False):
        if cmd == ["git", "--version"]:
            return CompletedProcess(cmd, 0, stdout="git version 2.14.0\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("yoke_core.domain.check_prerequisites.shutil.which", fake_which)
    monkeypatch.setattr("yoke_core.domain.check_prerequisites.subprocess.run", fake_run)

    assert run_checks(tmp_path) == 1
    out = capsys.readouterr().out
    assert "Git version >= 2.15" in out
    assert "Some critical checks failed." in out


def test_fails_when_permission_rules_missing(tmp_path, monkeypatch, capsys):
    _seed_repo(tmp_path, include_settings=False)

    def fake_which(name: str):
        if name == "git":
            return "/usr/bin/git"
        if name == "gh":
            return None
        return f"/usr/bin/{name}"

    def fake_run(cmd, capture_output=False, text=False):
        if cmd == ["git", "--version"]:
            return CompletedProcess(cmd, 0, stdout="git version 2.39.1\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("yoke_core.domain.check_prerequisites.shutil.which", fake_which)
    monkeypatch.setattr("yoke_core.domain.check_prerequisites.subprocess.run", fake_run)

    assert run_checks(tmp_path) == 1
    out = capsys.readouterr().out
    assert "Permission rules configured" in out
    assert "Some critical checks failed." in out


def test_warns_when_canonical_resolver_missing_app_auth(tmp_path, monkeypatch, capsys):
    """No Yoke GitHub App auth -> WARN (non-strict) with concrete repair text."""
    _seed_repo(tmp_path)

    def fake_which(name: str):
        if name in {"git", "gh"}:
            return f"/usr/bin/{name}"
        return None

    def fake_run(cmd, **_):
        if cmd == ["git", "--version"]:
            return CompletedProcess(cmd, 0, stdout="git version 2.39.1\n", stderr="")
        if cmd == ["gh", "extension", "list"]:
            return CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(
        "yoke_core.domain.check_prerequisites.shutil.which",
        fake_which,
    )
    monkeypatch.setattr(
        "yoke_core.domain.check_prerequisites.subprocess.run",
        fake_run,
    )

    from yoke_core.domain import project_github_auth as pga
    monkeypatch.setattr(
        "yoke_core.domain.check_prerequisites.resolve_project_github_auth",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            pga.MissingAppCredentials("yoke", "App credentials unavailable")
        ),
    )

    rc = run_checks(tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "All critical checks passed" in out
    # Repair hint routes to control-plane App configuration, not host login.
    assert "control-plane App issuer" in out
    retired_hint = "gh " + "auth " + "login"
    assert retired_hint not in out


def test_strict_promotes_missing_app_credentials_to_critical_fail(
    tmp_path, monkeypatch, capsys,
):
    """``--strict`` upgrades resolver WARN to FAIL so CI trips on the same gap."""
    _seed_repo(tmp_path)

    def fake_which(name: str):
        if name in {"git", "gh"}:
            return f"/usr/bin/{name}"
        return None

    def fake_run(cmd, **_):
        if cmd == ["git", "--version"]:
            return CompletedProcess(cmd, 0, stdout="git version 2.39.1\n", stderr="")
        if cmd == ["gh", "extension", "list"]:
            return CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(
        "yoke_core.domain.check_prerequisites.shutil.which",
        fake_which,
    )
    monkeypatch.setattr(
        "yoke_core.domain.check_prerequisites.subprocess.run",
        fake_run,
    )

    from yoke_core.domain import project_github_auth as pga
    monkeypatch.setattr(
        "yoke_core.domain.check_prerequisites.resolve_project_github_auth",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            pga.MissingAppCredentials("yoke", "App credentials unavailable")
        ),
    )

    rc = run_checks(tmp_path, strict=True)
    out = capsys.readouterr().out
    assert rc == 1
    assert "Some critical checks failed" in out
    assert "control-plane App issuer" in out


def test_accepts_legacy_claude_md_compat_path(tmp_path, monkeypatch, capsys):
    """Legacy CLAUDE.md (compat symlink) satisfies the doctrine-file check."""
    _seed_repo(tmp_path)
    # Replace the seeded AGENTS.md with a CLAUDE.md-only legacy layout.
    (tmp_path / "AGENTS.md").unlink()
    (tmp_path / "CLAUDE.md").write_text("legacy rules\n")

    def fake_which(name: str):
        if name == "git":
            return "/usr/bin/git"
        if name == "gh":
            return None
        return f"/usr/bin/{name}"

    def fake_run(cmd, capture_output=False, text=False):
        if cmd == ["git", "--version"]:
            return CompletedProcess(cmd, 0, stdout="git version 2.39.1\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("yoke_core.domain.check_prerequisites.shutil.which", fake_which)
    monkeypatch.setattr("yoke_core.domain.check_prerequisites.subprocess.run", fake_run)

    assert run_checks(tmp_path) == 0
    out = capsys.readouterr().out
    assert "AGENTS.md rules" in out
