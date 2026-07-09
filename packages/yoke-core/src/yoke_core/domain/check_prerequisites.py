"""Yoke prerequisite checks.

Yoke's GitHub operations run through bearer-token REST calls. The GitHub auth
check resolves through ``project_github_auth.resolve_project_github_auth``
(repo binding + short-lived GitHub App token).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)


ENTRYPOINT_CHECKS = (
    "packages/yoke-core/src/yoke_core/domain/check_prerequisites.py",
    "packages/yoke-core/src/yoke_core/domain/verify_overlap.py",
    "packages/yoke-core/src/yoke_core/domain/epic_task_sync.py",
    "packages/yoke-core/src/yoke_core/domain/update_status.py",
    "packages/yoke-core/src/yoke_core/engines/merge_worktree.py",
    "runtime/harness/claude/merge_settings.py",
)

REQUIRED_DIRECTORIES = (
    "docs",
    "packages/yoke-core/src/yoke_core",
)

AGENT_FILES = (
    "yoke-product-manager",
    "yoke-product-designer",
    "yoke-architect",
    "yoke-engineer",
    "yoke-tester",
    "yoke-simulator",
    "yoke-boss",
)

PERMISSION_RULES = (
    "Bash",
    "Write(**)",
    "Edit(**)",
    "Read(*)",
    "Grep(*)",
    "Glob(*)",
)


def _add_result(results: list[tuple[str, str]], check: str, status: str) -> None:
    results.append((check, status))


def _git_version_ok() -> bool:
    if not shutil.which("git"):
        return False
    result = subprocess.run(["git", "--version"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    version = result.stdout.strip().replace("git version ", "").split(" ", 1)[0]
    try:
        major_s, minor_s, *_rest = version.split(".")
        major, minor = int(major_s), int(minor_s)
    except Exception:
        return False
    return major > 2 or (major == 2 and minor >= 15)


def _git_common_dir(repo_root: Path) -> Path:
    dot_git = repo_root.joinpath(".git")
    if dot_git.is_dir():
        return dot_git
    if not dot_git.is_file():
        return dot_git

    first_line = dot_git.read_text(encoding="utf-8").splitlines()[0]
    prefix = "gitdir:"
    if not first_line.lower().startswith(prefix):
        return dot_git

    git_dir_text = first_line[len(prefix):].strip()
    git_dir = Path(git_dir_text)
    if not git_dir.is_absolute():
        git_dir = repo_root.joinpath(git_dir).resolve()

    common_dir_file = git_dir.joinpath("commondir")
    if common_dir_file.is_file():
        common_text = common_dir_file.read_text(encoding="utf-8").strip()
        common_dir = Path(common_text)
        if not common_dir.is_absolute():
            common_dir = git_dir.joinpath(common_dir).resolve()
        return common_dir

    return git_dir


def run_checks(repo_root: Path, *, strict: bool = False) -> int:
    critical_fail = False
    results: list[tuple[str, str]] = []
    auth_repair_hint: Optional[str] = None

    # Resolve project GitHub auth: PASS when Yoke's repo binding can produce a
    # bearer token, WARN with concrete repair text on resolver failures.
    # ``--strict`` upgrades WARN to FAIL so CI trips on the same gap.
    github_authed = False
    try:
        resolve_project_github_auth("yoke")
        github_authed = True
    except ProjectGithubAuthError as exc:
        auth_repair_hint = (
            f"project 'yoke' github auth not resolvable: {exc}. "
            f"Repair: {repair_command_hint(exc, 'yoke')}"
        )
    except Exception as exc:
        auth_repair_hint = (
            "project 'yoke' github auth not resolvable: "
            f"{type(exc).__name__}: {exc}"
        )
    if github_authed:
        _add_result(results, "Project GitHub App auth configured", "✅")
    elif strict:
        _add_result(results, "Project GitHub App auth configured", "❌")
        critical_fail = True
    else:
        _add_result(results, "Project GitHub App auth configured", "🚨")

    git_ok = _git_version_ok()
    _add_result(results, "Git version >= 2.15", "✅" if git_ok else "❌")
    critical_fail = critical_fail or not git_ok

    dirs_ok = all((repo_root / rel_path).is_dir() for rel_path in REQUIRED_DIRECTORIES)
    _add_result(results, "Directory structure", "✅" if dirs_ok else "❌")
    critical_fail = critical_fail or not dirs_ok

    agents_ok = all((repo_root / ".claude" / "agents" / f"{agent}.md").is_file() for agent in AGENT_FILES)
    _add_result(results, "Agent files in .claude/agents/", "✅" if agents_ok else "❌")
    critical_fail = critical_fail or not agents_ok

    canonical_agents = repo_root / "runtime" / "harness" / "claude" / "agents"
    canonical_agents_ok = all(
        (canonical_agents / f"{agent}.md").is_file() for agent in AGENT_FILES
    )
    _add_result(
        results,
        "Canonical agent sources in runtime/harness/claude/agents/",
        "✅" if canonical_agents_ok else "❌",
    )
    critical_fail = critical_fail or not canonical_agents_ok

    entrypoints_ok = all((repo_root / rel_path).is_file() for rel_path in ENTRYPOINT_CHECKS)
    _add_result(results, "Python entrypoints present", "✅" if entrypoints_ok else "❌")
    critical_fail = critical_fail or not entrypoints_ok

    pre_commit = _git_common_dir(repo_root).joinpath("hooks", "pre-commit")
    pre_commit_ok = (
        pre_commit.is_file()
        and os.access(pre_commit, os.X_OK)
        and "yoke-pre-commit" in pre_commit.read_text()
    )
    _add_result(results, "Git pre-commit hook", "✅" if pre_commit_ok else "❌")
    critical_fail = critical_fail or not pre_commit_ok

    settings = repo_root / ".claude" / "settings.json"
    settings_ok = settings.is_file() and all(rule in settings.read_text() for rule in PERMISSION_RULES)
    _add_result(results, "Permission rules configured", "✅" if settings_ok else "❌")
    critical_fail = critical_fail or not settings_ok

    canonical_settings = repo_root / "runtime" / "harness" / "claude" / "settings.json"
    canonical_settings_ok = canonical_settings.is_file()
    _add_result(
        results,
        "Canonical settings at runtime/harness/claude/settings.json",
        "✅" if canonical_settings_ok else "❌",
    )
    critical_fail = critical_fail or not canonical_settings_ok

    gitignore = repo_root / ".gitignore"
    gitignore_ok = gitignore.is_file()
    if gitignore_ok:
        text = gitignore.read_text()
        gitignore_ok = ".worktrees/" in text
    _add_result(results, ".gitignore updated", "✅" if gitignore_ok else "❌")
    critical_fail = critical_fail or not gitignore_ok

    # AGENTS.md is the canonical harness-neutral doctrine file. CLAUDE.md is
    # retained as a compatibility symlink so Claude Code's native auto-load
    # resolves the same content; .claude/CLAUDE.md is an older legacy path.
    doctrine_ok = (
        (repo_root / "AGENTS.md").is_file()
        or (repo_root / "CLAUDE.md").is_file()
        or (repo_root / ".claude" / "CLAUDE.md").is_file()
    )
    _add_result(results, "AGENTS.md rules", "✅" if doctrine_ok else "❌")
    critical_fail = critical_fail or not doctrine_ok

    print("┌─────────────────────────────────────┬────────┐")
    print("│ Check                               │ Status │")
    print("├─────────────────────────────────────┼────────┤")
    for check, status in results:
        print(f"│ {check:<33} │ {status:<6} │")
        print()
    print("└─────────────────────────────────────┴────────┘")

    print()
    if auth_repair_hint:
        print(auth_repair_hint)
        print()
    if critical_fail:
        print(
            "Some critical checks failed. Run `yoke project install` to "
            "repair the project layer, then `yoke status` for config "
            "diagnostics."
        )
        return 1
    print("All critical checks passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check-prerequisites",
        description="Validate Yoke prerequisite setup",
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Treat unresolvable project github auth as a critical "
            "failure (default is WARN, suitable for dev shells; CI "
            "should pass --strict)."
        ),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(run_checks(Path(args.repo_root), strict=args.strict))


if __name__ == "__main__":
    main()
