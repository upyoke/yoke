"""Project-declared disposable generated paths for lane-residue clearing.

The shared lane residue policy
(``yoke_core.engines.merge_worktree_cleanliness``) treats a small hardcoded
set of build/tool caches, plus the operating-layer state Yoke renders into
every checkout, as safe to remove from a retired lane. No project needs to
declare that Yoke-generated state. A project's own regenerated, gitignored
output — a rendered doc, a materialized asset directory — is exactly as
safe to remove, but that shared engine must never hardcode one project's
paths (Platform's build outputs have no business living in Yoke's source).
Each project instead declares its own list
through the ordinary ``project-policy`` capability key
``disposable_generated_paths``, validated here the same way on write and on
read so a rejected save and a refused stored value agree on the same rule.

This module stays free of any filesystem or database dependency, matching
``yoke_contracts.title_policy``: root-escape and symlink-escape are proven
against a real worktree by the shared residue policy itself, which already
applies that proof uniformly to every cache root, declared or built-in.
"""

from __future__ import annotations

from typing import Any, Optional

#: No project declares any additional disposable path until it opts in.
DISPOSABLE_GENERATED_PATHS_DEFAULT: list[str] = []


def disposable_generated_paths_setting_error(value: Any) -> Optional[str]:
    """Why a proposed ``disposable_generated_paths`` value is invalid, or ``None``.

    Shared by the settings-save validation path and the read-side resolver,
    so a rejected save and a refused stored declaration agree on the same
    rule: a JSON array of checkout-relative path strings, each free of a
    leading slash, a drive letter, or a ``..`` traversal segment.
    """
    if not isinstance(value, list):
        return (
            "disposable_generated_paths must be a JSON array of checkout-"
            f"relative path strings (got {value!r})."
        )
    for entry in value:
        error = _entry_error(entry)
        if error:
            return error
    return None


def _entry_error(entry: Any) -> Optional[str]:
    if not isinstance(entry, str) or not entry.strip():
        return (
            "disposable_generated_paths entries must be non-empty strings "
            f"(got {entry!r})."
        )
    normalized = entry.strip().replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        return (
            f"disposable_generated_paths entry {entry!r} must be checkout-"
            "relative, not absolute."
        )
    if not _normalized_parts(normalized) or ".." in normalized.split("/"):
        return (
            f"disposable_generated_paths entry {entry!r} must not traverse "
            "outside the checkout."
        )
    return None


def _normalized_parts(normalized: str) -> tuple[str, ...]:
    return tuple(part for part in normalized.split("/") if part not in ("", "."))


def parsed_disposable_generated_paths(value: Any) -> tuple[str, ...]:
    """Normalized, validated entries, or an empty tuple when *value* fails.

    Fail-closed: an invalid stored declaration disables project-declared
    paths for that read rather than widening what the shared residue policy
    treats as disposable, or raising into a cleanup path that must never
    crash.
    """
    if disposable_generated_paths_setting_error(value) is not None:
        return ()
    return tuple(
        "/".join(_normalized_parts(entry.strip().replace("\\", "/"))) for entry in value
    )


__all__ = [
    "DISPOSABLE_GENERATED_PATHS_DEFAULT",
    "disposable_generated_paths_setting_error",
    "parsed_disposable_generated_paths",
]
