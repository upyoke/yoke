"""Yoke prerequisite checks.

Yoke's GitHub operations run through bearer-token REST calls. The GitHub auth
check resolves through ``project_github_auth.resolve_project_github_auth``
(repo binding + short-lived GitHub App token).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from yoke_contracts.machine_config.checkout import LANES_DIR
from yoke_contracts.project_defaults import default_project_for_directory
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
    "Edit(**)",
    "Read",
    "Grep",
    "Glob",
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


def run_checks(repo_root: Path, *, strict: bool = False) -> int:
    critical_fail = False
    results: list[tuple[str, str]] = []
    auth_repair_hint: Optional[str] = None

    # Resolve the checkout's project GitHub auth: PASS when its repo binding
    # can produce a bearer token, WARN with concrete repair text on resolver
    # failures. ``--strict`` upgrades WARN to FAIL so CI trips on the same gap.
    github_authed = False
    project = default_project_for_directory(repo_root) or ""
    if not project:
        auth_repair_hint = (
            f"{repo_root} is not a registered project checkout, so no GitHub "
            "binding applies. Repair: yoke project register "
            f"{repo_root} --project-id <id>"
        )
    else:
        try:
            resolve_project_github_auth(project)
            github_authed = True
        except ProjectGithubAuthError as exc:
            auth_repair_hint = (
                f"project {project} github auth not resolvable: {exc}. "
                f"Repair: {repair_command_hint(exc, project)}"
            )
        except Exception as exc:
            auth_repair_hint = (
                f"project {project} github auth not resolvable: "
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

    agents_ok = all(
        (repo_root / ".claude" / "agents" / f"{agent}.md").is_file()
        for agent in AGENT_FILES
    )
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

    entrypoints_ok = all(
        (repo_root / rel_path).is_file() for rel_path in ENTRYPOINT_CHECKS
    )
    _add_result(results, "Python entrypoints present", "✅" if entrypoints_ok else "❌")
    critical_fail = critical_fail or not entrypoints_ok

    settings = repo_root / ".claude" / "settings.json"
    settings_ok = settings.is_file() and all(
        rule in settings.read_text(encoding="utf-8") for rule in PERMISSION_RULES
    )
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

    lanes_ignored = shutil.which("git") and subprocess.run(
        ["git", "-C", str(repo_root), "check-ignore", "-q", f"{LANES_DIR}/x"],
        capture_output=True,
    ).returncode == 0
    _add_result(results, "lanes ignored", "✅" if lanes_ignored else "❌")
    critical_fail = critical_fail or not lanes_ignored

    # Native shared doctrine has one canonical source.
    doctrine_ok = (repo_root / "AGENTS.md").is_file()
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
