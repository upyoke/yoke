"""Managed Git-hook payloads and ownership recognition."""

from __future__ import annotations

from typing import Any, List

# The three marker strings are single-sourced in yoke-contracts so yoke-core's
# doctor gate-liveness check can recognize an installed shim without importing
# yoke-cli. Re-exported here so this module's public API is unchanged.
from yoke_contracts.git_hook_markers import (
    POST_COMMIT_MARKER,
    PRE_COMMIT_MARKER,
    PRE_MERGE_COMMIT_MARKER,
)

GIT_HOOK_NAMES = ("pre-commit", "post-commit", "pre-merge-commit")


# A repository can reach a computer without Yoke (a synced folder, a plain
# clone). The shims find the launcher on PATH, then at the installer's
# launcher home, as the harness hooks do; with no launcher the commit goes
# through with one line of teaching, and CI plus the merge-queue preflight
# re-run the same authored-file checks. No absolute path is ever written in.
def _launcher_lookup(hook_name: str) -> str:
    return (
        "yoke_bin=$(command -v yoke 2>/dev/null) "
        '|| yoke_bin="${XDG_BIN_HOME:-$HOME/.local/bin}/yoke"\n'
        'if [ ! -x "$yoke_bin" ]; then\n'
        f'    echo "yoke ({hook_name}): Yoke is not installed on this computer ($(uname -n));'
        " Yoke checks skipped. Install:"
        ' \\`curl -fsSL https://upyoke.com/install | sh\\`" >&2\n'
        "    exit 0\n"
        "fi\n"
    )


PRE_COMMIT_SHIM = (
    "#!/bin/sh\n"
    f"# {PRE_COMMIT_MARKER} hook installed by `yoke project install`\n"
    "# Routes through the machine-installed `yoke` launcher (product\n"
    "# install or editable install) so hooked commits work without a Yoke\n"
    "# checkout importable by the ambient python3.\n"
    "# Hard-fails on gate violations.\n"
    + _launcher_lookup("pre-commit")
    + 'exec "$yoke_bin" git pre-commit "$@"\n'
)

POST_COMMIT_SHIM = (
    "#!/bin/sh\n"
    f"# {POST_COMMIT_MARKER} hook installed by `yoke project install`\n"
    "# Syncs committed git tree path snapshots for the project's HEAD so\n"
    "# downstream activate / boundary calls see current file metadata.\n"
    "# Harness-neutral: fires on every commit regardless of source\n"
    "# (agent tool calls, manual git commit, merge, rebase, cherry-pick).\n"
    "# Routes through the machine-installed `yoke` launcher; never\n"
    "# blocks — a completed commit must not fail on snapshot sync trouble.\n"
    + _launcher_lookup("post-commit")
    + 'exec "$yoke_bin" git post-commit "$@"\n'
)

PRE_MERGE_COMMIT_SHIM = (
    "#!/bin/sh\n"
    f"# {PRE_MERGE_COMMIT_MARKER} hook installed by `yoke project install`\n"
    "# git runs pre-commit only for `git commit`, so a merge that writes a\n"
    "# merge commit would otherwise skip the gate entirely and land files\n"
    "# no direct commit could. This runs the same staged-file gate before\n"
    "# the merge commit is written.\n"
    "# Hard-fails on gate violations.\n"
    + _launcher_lookup("pre-merge-commit")
    + 'exec "$yoke_bin" git pre-commit "$@"\n'
)

_MARKER_BY_HOOK = {
    "pre-commit": PRE_COMMIT_MARKER,
    "post-commit": POST_COMMIT_MARKER,
    "pre-merge-commit": PRE_MERGE_COMMIT_MARKER,
}

_SHIM_BY_HOOK = {
    "pre-commit": PRE_COMMIT_SHIM,
    "post-commit": POST_COMMIT_SHIM,
    "pre-merge-commit": PRE_MERGE_COMMIT_SHIM,
}


def is_managed_git_hook(content: str, hook_name: str) -> bool:
    """Recognize only the exact current managed hook payload."""
    expected = _SHIM_BY_HOOK.get(hook_name)
    if expected is None:
        return False
    return content == expected


def managed_git_hook_specs() -> List[dict[str, str]]:
    """Serializable managed-hook payload for bundles and local installs."""
    return [
        {
            "name": name,
            "marker": _MARKER_BY_HOOK[name],
            "content": _SHIM_BY_HOOK[name],
        }
        for name in GIT_HOOK_NAMES
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
                "managed_git_hooks entries must be unique known hook names "
                "carrying their stable Yoke marker and string content"
            )
        seen.add(name)
        specs.append({"name": name, "marker": marker, "content": content})
    if not seen:
        raise ValueError("managed_git_hooks must carry at least one managed hook")
    return specs


def git_hook_specs_from_bundle(bundle: dict[str, Any]) -> List[dict[str, str]]:
    """Select source-carried shims, or packaged shims for ordinary bundles.

    A bundle built before a managed hook existed simply omits it, so the
    packaged shim backfills the gap: every install lands the full managed
    set even while older bundles are still in circulation.
    """
    raw = bundle.get("managed_git_hooks")
    if raw is None:
        return managed_git_hook_specs()
    try:
        specs = validate_git_hook_specs(raw)
    except ValueError as exc:
        from yoke_cli.project_install.files import ProjectInstallError

        raise ProjectInstallError(str(exc)) from exc
    carried = {spec["name"] for spec in specs}
    specs.extend(
        spec for spec in managed_git_hook_specs() if spec["name"] not in carried
    )
    return specs


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


__all__ = [
    "GIT_HOOK_NAMES",
    "PRE_COMMIT_MARKER",
    "PRE_COMMIT_SHIM",
    "POST_COMMIT_MARKER",
    "POST_COMMIT_SHIM",
    "PRE_MERGE_COMMIT_MARKER",
    "PRE_MERGE_COMMIT_SHIM",
    "assert_pre_commit_runtime_available",
    "git_hook_specs_from_bundle",
    "is_managed_git_hook",
    "managed_git_hook_specs",
    "validate_git_hook_specs",
]
