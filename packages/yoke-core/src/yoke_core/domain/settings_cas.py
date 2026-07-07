"""Value-CAS primitives for the JSON settings writer surfaces.

``environments.settings`` and ``project_capabilities.settings`` are TEXT
columns with no version/``updated_at`` token, so the compare-and-swap token
is the as-read settings text itself: reads return the stored document,
full-document writes carry it back as ``--base``, and the UPDATE matches
only while the stored text still equals that base, guarding against the
live lost-update race where two writers overwrite each other's changes;
:mod:`yoke_core.domain.strategy_docs` owns the token-column variant of
the same fix). No schema change — the guard works on the TEXT columns
as-is, comparing the exact as-read text.

The merge loop is the collision-avoidance convenience: read → apply
key-path assignments → CAS-write, retrying once on conflict so two
writers touching different keys compose instead of erasing each other.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Dict, Optional, Sequence

#: Rendered document for an absent/NULL settings value; both surfaces
#: COALESCE to this on read and on the CAS match so a NULL column and the
#: empty object carry the same token.
EMPTY_SETTINGS_DOC = "{}"

#: Leading tag on every CAS-refusal message — the module-CLI mirror of the
#: strategy function-call envelope's ``replace_conflict`` error code.
SETTINGS_CONFLICT_TAG = "settings_conflict"


class SettingsConflictError(RuntimeError):
    """A CAS settings write was refused: the row moved past the base."""


def base_required_teaching(*, get_recipe: str, merge_recipe: str) -> str:
    """Usage teaching for a full-document write missing its base token."""
    return (
        "--base is required: full-document set-settings is compare-and-swap "
        "on the as-read settings text, so concurrent writers cannot "
        "silently erase each other. Flow: read the current document "
        f"({get_recipe}), edit it, then write it back passing the exact "
        "as-read text via --base. For single-key updates prefer the merge "
        f"surface ({merge_recipe}), which runs the read-merge-CAS cycle "
        "for you."
    )


def settings_conflict_teaching(
    *, what: str, get_recipe: str, merge_recipe: str
) -> str:
    """Canonical recovery teaching for a stale-base CAS refusal."""
    return (
        f"{SETTINGS_CONFLICT_TAG}: {what} changed in the DB after your "
        "--base text was read — refusing the full replace so the newer "
        f"document is not lost. Re-read it ({get_recipe}), re-apply your "
        "edit onto the fresh text, and retry with that fresh text as "
        f"--base; for single-key updates prefer {merge_recipe}."
    )


def parse_settings_object(
    settings_json: str, *, what: str = "settings JSON"
) -> Dict[str, Any]:
    """Parse and require a JSON object; raise loud ``ValueError`` otherwise."""
    try:
        parsed = json.loads(settings_json)
    except ValueError as exc:
        raise ValueError(f"Error: invalid {what}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Error: {what} must be a JSON object")
    return parsed


def parse_set_assignments(pairs: Sequence[str]) -> Dict[str, Any]:
    """Parse CLI ``key.path=value`` pairs into a dot-path assignment map.

    Values parse as JSON when they can (``true`` → bool, ``3`` → int,
    ``{"a":1}`` → object) and fall back to the raw string otherwise
    (``active`` → ``"active"``); quote JSON-style for an explicit string
    (``'"true"'``).
    """
    assignments: Dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        key = key.strip()
        if not sep or not key:
            raise ValueError(
                f"Error: invalid --set {pair!r}: expected key.path=value"
            )
        try:
            assignments[key] = json.loads(raw)
        except ValueError:
            assignments[key] = raw
    return assignments


def apply_key_path_assignments(
    doc: Dict[str, Any], assignments: Dict[str, Any]
) -> Dict[str, Any]:
    """Return a copy of ``doc`` with each dot-path assignment applied.

    Intermediate objects are created on demand; an existing non-object
    intermediate refuses loudly instead of being clobbered. Keys that
    themselves contain dots cannot be addressed through this surface.
    """
    merged = copy.deepcopy(doc)
    for path, value in assignments.items():
        parts = path.split(".")
        if any(not part for part in parts):
            raise ValueError(
                f"Error: invalid key path {path!r}: empty segment"
            )
        node = merged
        for part in parts[:-1]:
            child = node.get(part)
            if child is None:
                child = {}
                node[part] = child
            elif not isinstance(child, dict):
                raise ValueError(
                    f"Error: cannot set {path!r}: {part!r} holds a "
                    "non-object value"
                )
            node = child
        node[parts[-1]] = value
    return merged


def cas_merge_loop(
    *,
    read_current: Callable[[], Optional[str]],
    cas_write: Callable[[Optional[str], str], str],
    assignments: Dict[str, Any],
    what: str,
) -> str:
    """Read → merge → CAS-write with one retry on conflict.

    ``read_current`` returns the as-read settings text (``None`` when the
    target row/document is absent — the merge then starts from the empty
    object and ``cas_write`` receives ``None`` as the base, signalling the
    create path). A second consecutive conflict propagates the typed
    :class:`SettingsConflictError` — by then a live writer is contending
    and the caller must re-drive explicitly.
    """
    if not assignments:
        raise ValueError(
            "Error: at least one key.path=value assignment is required"
        )
    last_conflict: Optional[SettingsConflictError] = None
    for _ in range(2):
        base = read_current()
        doc = (
            {}
            if base is None
            else parse_settings_object(base, what=f"stored {what}")
        )
        merged_text = json.dumps(apply_key_path_assignments(doc, assignments))
        try:
            return cas_write(base, merged_text)
        except SettingsConflictError as exc:
            last_conflict = exc
    assert last_conflict is not None
    raise last_conflict
