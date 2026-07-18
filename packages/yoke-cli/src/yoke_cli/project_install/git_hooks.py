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

Semantics: existing foreign or ambiguous marker-bearing hooks are left in
place with a warning; exact current/historical shims or manifest-hash-owned
shims are refreshed; missing hooks are created. Linked worktrees share the
main checkout's ``.git/hooks/``
(their ``.git`` is a file, reported as skipped) — run the install from
the main checkout. Distinct from the sibling :mod:`hooks` module, which
merges the bundle's HARNESS hook config into ``.claude/settings.json``
and ``.codex/hooks.json``.
"""

from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

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

# Exact historical bytes that the installer itself shipped before launcher
# routing.  These may be upgraded safely; arbitrary marker-bearing composites
# are never ownership evidence.
_LEGACY_PRE_COMMIT_SHIMS = frozenset({
    (
        "#!/bin/sh\n"
        f"# {PRE_COMMIT_MARKER} hook installed by `yoke project install`\n"
        "# Hard-fails on file_line_check violations. "
        "Bypass with `git commit --no-verify`.\n"
        'exec python3 -m yoke_core.domain.git_pre_commit "$@"\n'
    ),
})
_LEGACY_POST_COMMIT_SHIMS = frozenset({
    (
        "#!/bin/sh\n"
        f"# {POST_COMMIT_MARKER} hook installed by `yoke project install`\n"
        "# Pre-warms the path-snapshot cache for the project's HEAD so that\n"
        "# downstream activate / boundary calls never hit a cold-start miss.\n"
        "# Harness-neutral: fires on every commit regardless of source\n"
        "# (agent tool calls, manual git commit, merge, rebase, cherry-pick).\n"
        "exec python3 -m yoke_core.domain.path_snapshots --ensure-head"
        ' "${YOKE_PROJECT_ID:-yoke}" >/dev/null 2>&1\n'
    ),
})

_MARKER_BY_HOOK = {
    "pre-commit": PRE_COMMIT_MARKER,
    "post-commit": POST_COMMIT_MARKER,
}
def is_managed_git_hook(content: str, hook_name: str) -> bool:
    """Recognize only exact current or enumerated historical shim bytes."""
    expected = PRE_COMMIT_SHIM if hook_name == "pre-commit" else POST_COMMIT_SHIM
    legacy = (
        _LEGACY_PRE_COMMIT_SHIMS
        if hook_name == "pre-commit"
        else _LEGACY_POST_COMMIT_SHIMS
    )
    return content == expected or content in legacy


def managed_git_hook_specs() -> List[dict[str, str]]:
    """Serializable managed-hook payload for bundles and local installs."""
    return [
        {
            "name": "pre-commit",
            "marker": PRE_COMMIT_MARKER,
            "content": PRE_COMMIT_SHIM,
        },
        {
            "name": "post-commit",
            "marker": POST_COMMIT_MARKER,
            "content": POST_COMMIT_SHIM,
        },
    ]


def validate_git_hook_specs(raw_specs: Any) -> List[dict[str, str]]:
    """Validate the fixed-name source-selected managed-hook payload."""
    if not isinstance(raw_specs, list):
        raise ValueError("managed_git_hooks must be an array")
    specs: List[dict[str, str]] = []
    seen = set()
    for raw in raw_specs:
        if not isinstance(raw, dict):
            raise ValueError("managed_git_hooks entries must be objects")
        name = raw.get("name")
        marker = raw.get("marker")
        content = raw.get("content")
        if (
            name not in GIT_HOOK_NAMES
            or name in seen
            or not isinstance(marker, str)
            or marker != _MARKER_BY_HOOK[name]
            or not isinstance(content, str)
            or marker not in content
        ):
            raise ValueError(
                "managed_git_hooks must carry unique pre-commit/post-commit "
                "entries with their stable Yoke marker and string content"
            )
        seen.add(name)
        specs.append({"name": name, "marker": marker, "content": content})
    if seen != set(GIT_HOOK_NAMES):
        raise ValueError("managed_git_hooks must carry both managed hook names")
    return specs


def git_hook_specs_from_bundle(bundle: dict[str, Any]) -> List[dict[str, str]]:
    """Select source-carried shims, or packaged shims for ordinary bundles."""
    raw = bundle.get("managed_git_hooks")
    if raw is None:
        return managed_git_hook_specs()
    try:
        return validate_git_hook_specs(raw)
    except ValueError as exc:
        from yoke_cli.project_install.files import ProjectInstallError

        raise ProjectInstallError(str(exc)) from exc


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
    owned_hashes: dict[str, str] | None = None,
) -> None:
    """Write the ``.git/hooks/<hook_name>`` shim. Idempotent."""
    from yoke_cli.project_install.files import assert_resolved_targets_within

    assert_resolved_targets_within(
        target_root,
        [f".git/hooks/{hook_name}"],
        context="managed git hook mutation",
    )
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
        rel = f".git/hooks/{hook_name}"
        digest = hashlib.sha256(existing.encode("utf-8")).hexdigest()
        manifest_owned = (
            owned_hashes is not None and owned_hashes.get(rel) == digest
        )
        if not manifest_owned and not is_managed_git_hook(existing, hook_name):
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


def install_git_hooks(
    target_root: Path,
    result: BootstrapResult,
    specs: List[dict[str, str]] | None = None,
    owned_hashes: dict[str, str] | None = None,
) -> None:
    """Install both Yoke git hook shims (shared by both strategies)."""
    selected = managed_git_hook_specs() if specs is None else specs
    try:
        selected = validate_git_hook_specs(selected)
    except ValueError as exc:
        from yoke_cli.project_install.files import ProjectInstallError

        raise ProjectInstallError(str(exc)) from exc
    for spec in selected:
        install_git_hook(
            target_root,
            spec["name"],
            spec["marker"],
            spec["content"],
            result,
            owned_hashes,
        )


def preview_git_hooks(
    target_root: Path,
    specs: List[dict[str, str]],
    owned_hashes: dict[str, str] | None = None,
) -> BootstrapResult:
    """Return the complete managed-hook convergence plan without writes."""
    from yoke_cli.project_install.files import assert_resolved_targets_within

    try:
        selected = validate_git_hook_specs(specs)
    except ValueError as exc:
        from yoke_cli.project_install.files import ProjectInstallError

        raise ProjectInstallError(str(exc)) from exc
    result = BootstrapResult()
    assert_resolved_targets_within(
        target_root,
        [f".git/hooks/{spec['name']}" for spec in selected],
        context="managed git hook mutation",
    )
    hooks_dir = target_root / ".git" / "hooks"
    for spec in selected:
        hook_path = hooks_dir / spec["name"]
        if not hooks_dir.is_dir():
            result.note(
                f"Skipped: .git/hooks/{spec['name']} (.git/hooks/ does not "
                "exist — not a git repo, or a linked worktree sharing the "
                "main checkout's .git)"
            )
            continue
        if hook_path.exists():
            try:
                existing = hook_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                existing = ""
            rel = f".git/hooks/{spec['name']}"
            digest = hashlib.sha256(existing.encode("utf-8")).hexdigest()
            manifest_owned = (
                owned_hashes is not None and owned_hashes.get(rel) == digest
            )
            if not manifest_owned and not is_managed_git_hook(
                existing, spec["name"],
            ):
                result.warn(
                    f".git/hooks/{spec['name']} exists and is not "
                    "Yoke-managed. Refusing to overwrite."
                )
            elif existing == spec["content"]:
                result.note(
                    f"Exists: .git/hooks/{spec['name']} (Yoke-managed, up to date)"
                )
            else:
                result.note(f"Would update: .git/hooks/{spec['name']}")
                result.updated += 1
        else:
            result.note(f"Would create: .git/hooks/{spec['name']}")
            result.installed += 1
    return result


def managed_git_hook_hashes(
    target_root: Path, specs: List[dict[str, str]],
) -> dict[str, str]:
    """Hash only exact selected shims currently present on disk."""
    hashes = {}
    for spec in validate_git_hook_specs(specs):
        rel = f".git/hooks/{spec['name']}"
        target = target_root / rel
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if content == spec["content"]:
            hashes[rel] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return hashes


def remove_yoke_git_hooks(
    target_root: Path, owned_hashes: dict[str, str] | None = None,
) -> List[str]:
    """Uninstall pass: remove exactly owned git hook shims only.

    Foreign hooks (no marker) are never touched. Returns the removed
    hook names. Used by copy-mode uninstall; source-link uninstall
    refuses before reaching here.
    """
    from yoke_cli.project_install.files import assert_resolved_targets_within

    assert_resolved_targets_within(
        target_root,
        [f".git/hooks/{name}" for name in GIT_HOOK_NAMES],
        context="managed git hook removal",
    )
    removed: List[str] = []
    for hook_name in GIT_HOOK_NAMES:
        hook_path = target_root / ".git" / "hooks" / hook_name
        if not hook_path.is_file():
            continue
        try:
            existing = hook_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = f".git/hooks/{hook_name}"
        digest = hashlib.sha256(existing.encode("utf-8")).hexdigest()
        exact_manifest_owner = (
            owned_hashes is not None and owned_hashes.get(rel) == digest
        )
        legacy_shape_owner = owned_hashes is None and is_managed_git_hook(
            existing, hook_name,
        )
        if exact_manifest_owner or legacy_shape_owner:
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
    "git_hook_specs_from_bundle",
    "install_pre_commit_hook",
    "install_post_commit_hook",
    "is_managed_git_hook",
    "managed_git_hook_specs",
    "managed_git_hook_hashes",
    "preview_git_hooks",
    "remove_yoke_git_hooks",
    "validate_git_hook_specs",
]
