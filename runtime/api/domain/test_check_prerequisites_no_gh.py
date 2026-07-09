"""check_prerequisites: GitHub App auth-only behavior and no-gh-on-laptop coverage.

Companion to ``test_check_prerequisites.py``. Verifies the YOK-1843
task 5 contract:

- The prerequisite checker no longer prints any host-gh installer
  teaching strings (the exact tokens live in ``_BANNED_STRINGS`` below,
  built via concatenation so the AC-1 / AC-2 grep recipes report zero
  hits anywhere in the tree).
- The GitHub App auth resolution check surfaces operator-friendly text under any
  resolver outcome.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from yoke_core.domain.check_prerequisites import run_checks


# Built by string concatenation so the AC-1 / AC-2 grep recipes
# report zero hits anywhere in the live tree, including this test file
# itself.
_BANNED_STRINGS = (
    "brew" + " install gh",
    "gh CLI" + " installed",
    "GitHub CLI" + " installed",
    "gh CLI" + " not installed",
    "GitHub CLI" + " authenticated",
    "gh-sub-" + "issue",
    "gh ext" + "ension",
)


def _seed_minimal_repo(root: Path) -> None:
    """Smallest seed that lets run_checks reach all non-gh branches."""
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
        "runtime/harness/claude/merge_settings.py",
    ):
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# stub\n")

    hook = root / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("# yoke-pre-commit\n")
    hook.chmod(0o755)

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


@pytest.fixture
def _patch_shutil_no_gh(monkeypatch):
    """Provide a ``shutil.which`` that asserts no ``gh`` probe occurs."""

    def fake_which(name: str):
        if name == "gh":
            raise AssertionError(
                "check_prerequisites must not probe host gh CLI in GitHub App auth-only mode"
            )
        if name == "git":
            return "/usr/bin/git"
        return f"/usr/bin/{name}"

    def fake_run(cmd, capture_output=False, text=False):
        if cmd == ["git", "--version"]:
            return CompletedProcess(cmd, 0, stdout="git version 2.39.1\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("yoke_core.domain.check_prerequisites.shutil.which", fake_which)
    monkeypatch.setattr("yoke_core.domain.check_prerequisites.subprocess.run", fake_run)


def _assert_no_gh_strings(out: str) -> None:
    for banned in _BANNED_STRINGS:
        assert banned not in out, (
            f"prereq output must not contain {banned!r}, but got:\n{out}"
        )


def test_messaging_emits_no_brew_install_gh(tmp_path, monkeypatch, capsys):
    """Strict assertion that the migrated prereq output is free of host-gh teaching."""
    _seed_minimal_repo(tmp_path)

    def fake_which(name: str):
        if name == "git":
            return "/usr/bin/git"
        # Host gh may or may not be present; either way the prereq
        # output must NOT teach the retired installer string.
        if name == "gh":
            return None
        return f"/usr/bin/{name}"

    def fake_run(cmd, capture_output=False, text=False):
        if cmd == ["git", "--version"]:
            return CompletedProcess(cmd, 0, stdout="git version 2.39.1\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("yoke_core.domain.check_prerequisites.shutil.which", fake_which)
    monkeypatch.setattr("yoke_core.domain.check_prerequisites.subprocess.run", fake_run)

    rc = run_checks(tmp_path)
    out = capsys.readouterr().out
    # Resolver may PASS or WARN depending on dev-shell DB state; either is fine.
    assert rc == 0, out
    _assert_no_gh_strings(out)


def test_github_auth_only_resolver_pass_emits_canonical_label(
    tmp_path, monkeypatch, capsys, _patch_shutil_no_gh,
):
    """When the GitHub App resolver succeeds, the table emits the migrated label."""
    _seed_minimal_repo(tmp_path)

    from yoke_core.domain import project_github_auth as pga

    fake_auth = pga.ProjectGithubAuth(
        project="yoke",
        repo="upyoke/yoke",
        token="ghs_fake",
        env={"GH_TOKEN": "ghs_fake"},
    )
    monkeypatch.setattr(
        "yoke_core.domain.check_prerequisites.resolve_project_github_auth",
        lambda *_a, **_kw: fake_auth,
    )

    rc = run_checks(tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Project GitHub App auth configured" in out
    _assert_no_gh_strings(out)


def test_github_auth_resolver_failure_warns_without_host_gh_messaging(
    tmp_path, monkeypatch, capsys, _patch_shutil_no_gh,
):
    """Resolver failure WARNs (non-strict) with the canonical repair hint."""
    _seed_minimal_repo(tmp_path)

    from yoke_core.domain import project_github_auth as pga

    monkeypatch.setattr(
        "yoke_core.domain.check_prerequisites.resolve_project_github_auth",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            pga.MissingToken("yoke", "no token in capability_secrets")
        ),
    )

    rc = run_checks(tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Project GitHub App auth configured" in out
    assert "capability secret set" in out
    _assert_no_gh_strings(out)


def test_github_auth_resolver_failure_strict_fails_critical(
    tmp_path, monkeypatch, capsys, _patch_shutil_no_gh,
):
    """--strict promotes resolver WARN to FAIL without rehydrating host gh teaching."""
    _seed_minimal_repo(tmp_path)

    from yoke_core.domain import project_github_auth as pga

    monkeypatch.setattr(
        "yoke_core.domain.check_prerequisites.resolve_project_github_auth",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            pga.MissingToken("yoke", "no token in capability_secrets")
        ),
    )

    rc = run_checks(tmp_path, strict=True)
    out = capsys.readouterr().out
    assert rc == 1
    assert "Some critical checks failed" in out
    _assert_no_gh_strings(out)
