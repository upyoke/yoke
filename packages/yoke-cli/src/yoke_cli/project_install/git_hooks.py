"""Git hook shims for ``yoke project install`` (both strategies).

Owns the ``.git/hooks/pre-commit`` shim (product-safe local file-line
gate) and the ``post-commit`` shim (product-safe committed-tree snapshot
sync through ``yoke project snapshot sync --hook --head-only``). Both
shims exec the machine-installed
``yoke`` launcher — ``yoke git pre-commit`` / ``yoke git
post-commit`` (:mod:`yoke_cli.commands.git_hook`) — so
hooked commits work without a Yoke checkout importable by the
ambient ``python3``. ``.git/hooks/`` is per-clone and never
tracked, so the installer is the primary install surface for both
hooks in every checkout — external project repos (copy strategy) and
the Yoke source checkout (source-link strategy) alike.

Semantics: existing non-Yoke hooks are left in place with a warning;
Yoke-marked hooks with drifted content are refreshed; missing hooks
are created. Linked worktrees share the main checkout's ``.git/hooks/``
(their ``.git`` is a file, reported as skipped) — run the install from
the main checkout. Distinct from the sibling :mod:`hooks` module, which
merges the bundle's HARNESS hook config into ``.claude/settings.json``
and ``.codex/hooks.json``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL

GIT_HOOK_NAMES = ("pre-commit", "post-commit")

# Reinstall hint printed when a hooked commit runs on a machine whose `yoke`
# launcher is missing. The official distribution channel is the default; a
# machine installed from another channel reruns its own installer command.
INSTALL_COMMAND_HINT = f"curl -fsSL {DISTRIBUTION_PROD_URL}/install | bash"

PRE_COMMIT_MARKER = "yoke-pre-commit"
PRE_COMMIT_SHIM = (
    "#!/bin/sh\n"
    f"# {PRE_COMMIT_MARKER} hook installed by `yoke project install`\n"
    "# Routes through the machine-installed `yoke` launcher (product\n"
    "# install or editable install) so hooked commits work without a Yoke\n"
    "# checkout importable by the ambient python3.\n"
    "# Hard-fails on gate violations. Bypass with `git commit --no-verify`.\n"
    "if ! command -v yoke >/dev/null 2>&1; then\n"
    "    echo \"yoke pre-commit hook: 'yoke' launcher not on PATH —\" >&2\n"
    "    echo \"install or repair the machine CLI with the public installer:\" >&2\n"
    f"    echo \"{INSTALL_COMMAND_HINT}\" >&2\n"
    "    echo \"or bypass once with 'git commit --no-verify'.\" >&2\n"
    "    exit 1\n"
    "fi\n"
    "exec yoke git pre-commit \"$@\"\n"
)

POST_COMMIT_MARKER = "yoke-post-commit"
POST_COMMIT_SHIM = (
    "#!/bin/sh\n"
    f"# {POST_COMMIT_MARKER} hook installed by `yoke project install`\n"
    "# Syncs committed git tree path snapshots for the project's HEAD so\n"
    "# downstream activate / boundary calls see current file metadata.\n"
    "# Harness-neutral: fires on every commit regardless of source\n"
    "# (agent tool calls, manual git commit, merge, rebase, cherry-pick).\n"
    "# Routes through the machine-installed `yoke` launcher; never\n"
    "# blocks — a completed commit must not fail on snapshot sync trouble.\n"
    "if ! command -v yoke >/dev/null 2>&1; then\n"
    "    echo \"yoke post-commit hook: 'yoke' launcher not on PATH —\" >&2\n"
    "    echo \"path snapshot sync skipped; repair with the public installer:\" >&2\n"
    f"    echo \"{INSTALL_COMMAND_HINT}\" >&2\n"
    "    exit 0\n"
    "fi\n"
    "exec yoke git post-commit \"$@\"\n"
)

_MARKER_BY_HOOK = {
    "pre-commit": PRE_COMMIT_MARKER,
    "post-commit": POST_COMMIT_MARKER,
}


def assert_pre_commit_runtime_available() -> None:
    """Fail before project writes when the installed gate cannot import."""
    try:
        from yoke_harness.git_hooks.pre_commit import run as _run
    except ImportError as exc:
        from yoke_cli.project_install.files import ProjectInstallError

        raise ProjectInstallError(
            "project install requires the yoke-harness product package before "
            "it can install the pre-commit shim; repair the machine CLI with "
            f"the public installer ({exc})"
        ) from exc
    if not callable(_run):
        from yoke_cli.project_install.files import ProjectInstallError

        raise ProjectInstallError(
            "the installed yoke-harness pre-commit entrypoint is not callable; "
            "repair the machine CLI with the public installer"
        )


@dataclass
class BootstrapResult:
    """Tally + human-readable action lines for the install report."""

    installed: int = 0
    updated: int = 0
    skipped: int = 0
    actions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def note(self, line: str) -> None:
        self.actions.append(line)

    def warn(self, line: str) -> None:
        self.warnings.append(line)


def install_git_hook(
    target_root: Path,
    hook_name: str,
    marker: str,
    shim: str,
    result: BootstrapResult,
) -> None:
    """Write the ``.git/hooks/<hook_name>`` shim. Idempotent."""
    hooks_dir = target_root / ".git" / "hooks"
    if not hooks_dir.is_dir():
        result.note(
            f"Skipped: .git/hooks/{hook_name} (.git/hooks/ does not exist — "
            "not a git repo, or a linked worktree sharing the main "
            "checkout's .git)"
        )
        return

    hook_path = hooks_dir / hook_name
    if hook_path.exists():
        try:
            existing = hook_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            existing = ""
        if marker not in existing:
            result.warn(
                f".git/hooks/{hook_name} exists and is not Yoke-managed. "
                "Refusing to overwrite. Move it aside and re-run "
                "`yoke project install` to install the Yoke hook."
            )
            return
        if existing == shim:
            result.note(
                f"Exists: .git/hooks/{hook_name} (Yoke-managed, up to date)"
            )
            return
        hook_path.write_text(shim, encoding="utf-8")
        os.chmod(hook_path, 0o755)
        result.note(f"Updated: .git/hooks/{hook_name}")
        result.updated += 1
        return

    hook_path.write_text(shim, encoding="utf-8")
    os.chmod(hook_path, 0o755)
    result.note(f"Created: .git/hooks/{hook_name}")
    result.installed += 1


def install_pre_commit_hook(target_root: Path, result: BootstrapResult) -> None:
    """Install the product-local pre-commit gate shim."""
    install_git_hook(
        target_root, "pre-commit", PRE_COMMIT_MARKER, PRE_COMMIT_SHIM, result,
    )


def install_post_commit_hook(target_root: Path, result: BootstrapResult) -> None:
    """Install the post-commit path snapshot sync shim."""
    install_git_hook(
        target_root, "post-commit", POST_COMMIT_MARKER, POST_COMMIT_SHIM, result,
    )


def install_git_hooks(target_root: Path, result: BootstrapResult) -> None:
    """Install both Yoke git hook shims (shared by both strategies)."""
    install_pre_commit_hook(target_root, result)
    install_post_commit_hook(target_root, result)


def remove_yoke_git_hooks(target_root: Path) -> List[str]:
    """Uninstall pass: remove Yoke-MARKED git hook shims only.

    Foreign hooks (no marker) are never touched. Returns the removed
    hook names. Used by copy-mode uninstall; source-link uninstall
    refuses before reaching here.
    """
    removed: List[str] = []
    for hook_name in GIT_HOOK_NAMES:
        hook_path = target_root / ".git" / "hooks" / hook_name
        if not hook_path.is_file():
            continue
        try:
            existing = hook_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _MARKER_BY_HOOK[hook_name] in existing:
            hook_path.unlink()
            removed.append(hook_name)
    return removed


__all__ = [
    "GIT_HOOK_NAMES",
    "PRE_COMMIT_MARKER",
    "PRE_COMMIT_SHIM",
    "POST_COMMIT_MARKER",
    "POST_COMMIT_SHIM",
    "BootstrapResult",
    "assert_pre_commit_runtime_available",
    "install_git_hook",
    "install_git_hooks",
    "install_pre_commit_hook",
    "install_post_commit_hook",
    "remove_yoke_git_hooks",
]
