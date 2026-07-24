"""Managed Git-hook payloads and ownership recognition."""

from __future__ import annotations

from typing import Any, List

from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL

GIT_HOOK_NAMES = ("pre-commit", "post-commit", "pre-merge-commit")

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
    '    echo "install or repair the machine CLI with the public installer:" >&2\n'
    f'    echo "{INSTALL_COMMAND_HINT}" >&2\n'
    "    echo \"or bypass once with 'git commit --no-verify'.\" >&2\n"
    "    exit 1\n"
    "fi\n"
    'exec yoke git pre-commit "$@"\n'
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
    '    echo "path snapshot sync skipped; repair with the public installer:" >&2\n'
    f'    echo "{INSTALL_COMMAND_HINT}" >&2\n'
    "    exit 0\n"
    "fi\n"
    'exec yoke git post-commit "$@"\n'
)

PRE_MERGE_COMMIT_MARKER = "yoke-pre-merge-commit"
PRE_MERGE_COMMIT_SHIM = (
    "#!/bin/sh\n"
    f"# {PRE_MERGE_COMMIT_MARKER} hook installed by `yoke project install`\n"
    "# git runs pre-commit only for `git commit`, so a merge that writes a\n"
    "# merge commit would otherwise skip the gate entirely and land files\n"
    "# no direct commit could. This runs the same staged-file gate before\n"
    "# the merge commit is written.\n"
    "# Hard-fails on gate violations. Bypass with `git merge --no-verify`.\n"
    "if ! command -v yoke >/dev/null 2>&1; then\n"
    "    echo \"yoke pre-merge-commit hook: 'yoke' launcher not on PATH —\" >&2\n"
    '    echo "install or repair the machine CLI with the public installer:" >&2\n'
    f'    echo "{INSTALL_COMMAND_HINT}" >&2\n'
    "    echo \"or bypass once with 'git merge --no-verify'.\" >&2\n"
    "    exit 1\n"
    "fi\n"
    'exec yoke git pre-commit "$@"\n'
)

# Exact historical bytes that the installer itself shipped before launcher
# routing.  These may be upgraded safely; arbitrary marker-bearing composites
# are never ownership evidence.
_LEGACY_PRE_COMMIT_SHIMS = frozenset(
    {
        (
            "#!/bin/sh\n"
            f"# {PRE_COMMIT_MARKER} hook installed by `yoke project install`\n"
            "# Hard-fails on file_line_check violations. "
            "Bypass with `git commit --no-verify`.\n"
            'exec python3 -m yoke_core.domain.git_pre_commit "$@"\n'
        ),
    }
)
_LEGACY_POST_COMMIT_SHIMS = frozenset(
    {
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
    }
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

_LEGACY_SHIMS_BY_HOOK: dict[str, frozenset[str]] = {
    "pre-commit": _LEGACY_PRE_COMMIT_SHIMS,
    "post-commit": _LEGACY_POST_COMMIT_SHIMS,
    "pre-merge-commit": frozenset(),
}


def is_managed_git_hook(content: str, hook_name: str) -> bool:
    """Recognize only exact current or enumerated historical shim bytes."""
    expected = _SHIM_BY_HOOK.get(hook_name)
    if expected is None:
        return False
    legacy = _LEGACY_SHIMS_BY_HOOK.get(hook_name, frozenset())
    return content == expected or content in legacy


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
