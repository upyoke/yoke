"""GitHub label color policy — the single source shared by client and server.

This lives in ``yoke_contracts`` (the dependency-light package both the CLI
and the core engine import) so the default colors are defined exactly once:

- the project-contract installer seeds ``.yoke/labels`` from these defaults,
- the client computes its per-project override *delta* against these defaults,
- the server applies ``override-else-default`` from these same defaults.

Because both halves read this one definition, the defaults can never drift and
no half has to reach into the other's runtime modules to learn them.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple

# (github label name, policy key, default hex, description). The policy key is
# the ``label_color_*`` knob a project may override in ``.yoke/labels``.
REPO_LABEL_DEFINITIONS: Tuple[Tuple[str, str, str, str], ...] = (
    ("type:epic", "label_color_type_epic", "5319E7", "Epic (parent issue)"),
    ("type:task", "label_color_type_task", "0E8A16", "Task (child of epic)"),
    ("type:issue", "label_color_type_issue", "1D76DB", "Issue (backlog item)"),
    ("type:integration-fix", "label_color_type_integration_fix", "D93F0B", "Integration fix"),
    ("priority:high", "label_color_priority_high", "D93F0B", "High priority"),
    ("priority:medium", "label_color_priority_medium", "C5DEF5", "Medium priority"),
    ("priority:low", "label_color_priority_low", "0E8A16", "Low priority"),
    ("status:idea", "label_color_status_idea", "D4C5F9", "Status: idea"),
    ("status:refining-idea", "label_color_status_refining_idea", "C5DEF5", "Status: refining-idea"),
    ("status:refined-idea", "label_color_status_refined_idea", "BFD4F2", "Status: refined-idea"),
    ("status:planning", "label_color_status_planning", "A2EEEF", "Status: planning"),
    ("status:refining-plan", "label_color_status_refining_plan", "7FDBCA", "Status: refining-plan"),
    ("status:planned", "label_color_status_planned", "7FDBCA", "Status: planned"),
    ("status:implementing", "label_color_status_implementing", "0E8A16", "Status: implementing"),
    ("status:reviewing-implementation", "label_color_status_reviewing_implementation", "FBCA04", "Status: reviewing-implementation"),
    ("status:reviewed-implementation", "label_color_status_reviewed_implementation", "FEF2C0", "Status: reviewed-implementation"),
    ("status:polishing-implementation", "label_color_status_polishing_implementation", "5319E7", "Status: polishing-implementation"),
    ("status:implemented", "label_color_status_implemented", "0E8A16", "Status: implemented"),
    ("status:release", "label_color_status_release", "6F42C1", "Status: release"),
    ("status:done", "label_color_status_done", "0E8A16", "Status: done"),
    ("status:cancelled", "label_color_status_cancelled", "BFD4F2", "Status: cancelled"),
    ("status:failed", "label_color_status_failed", "D93F0B", "Status: failed"),
    # The flag-driven "blocked" label (no `status:` prefix) is the live one;
    # any legacy `status:blocked` label is scrubbed by the repair sweep.
    ("status:stopped", "label_color_status_stopped", "E4E669", "Status: stopped"),
    ("blocked", "label_color_blocked", "B60205", "Item blocked (flag)"),
)

# Default colors for the generic dynamic label families (status/source/owner/
# worktree) and flags that are not row-per-value in REPO_LABEL_DEFINITIONS.
DEFAULT_COLOR_STATUS = "C5DEF5"
DEFAULT_COLOR_TYPE_EPIC = "5319E7"
DEFAULT_COLOR_TYPE_ISSUE = "1D76DB"
DEFAULT_COLOR_SOURCE = "0e8a16"
DEFAULT_COLOR_OWNER = "BFD4F2"
DEFAULT_COLOR_WORKTREE = "D4C5F9"
FROZEN_LABEL_COLOR = "c0e0ff"
BLOCKED_LABEL_COLOR = "B60205"

# The complete default color map: every policy key -> its default hex. This is
# the baseline the client diffs against and the server falls back to.
DEFAULT_LABEL_COLORS: Dict[str, str] = {
    key: value for _category, key, value, _description in REPO_LABEL_DEFINITIONS
}
DEFAULT_LABEL_COLORS.update(
    {
        "label_color_status": DEFAULT_COLOR_STATUS,
        "label_color_source": DEFAULT_COLOR_SOURCE,
        "label_color_owner": DEFAULT_COLOR_OWNER,
        "label_color_worktree": DEFAULT_COLOR_WORKTREE,
        "label_color_frozen": FROZEN_LABEL_COLOR,
    }
)


def resolve_color(
    key: str,
    overrides: Optional[Mapping[str, str]] = None,
    default: Optional[str] = None,
) -> Optional[str]:
    """Color for *key*: a client *override*, else the contract default, else *default*.

    The server passes the per-request override map (resolved client-side); it
    never reads a file. ``default`` is a last-resort for keys absent from the
    contract map (e.g. an unrecognized priority).
    """
    if overrides:
        override = overrides.get(key)
        if override:
            return override
    return DEFAULT_LABEL_COLORS.get(key) or default


def overrides_delta(file_values: Mapping[str, str]) -> Dict[str, str]:
    """The subset of ``.yoke/labels`` entries that differ from the defaults.

    Comparison is case-insensitive (hex color case is not significant), so a
    file that merely restates a default contributes no override. Unknown keys
    (no contract default) are treated as overrides.
    """
    delta: Dict[str, str] = {}
    for key, value in file_values.items():
        if not value:
            continue
        if value.upper() != DEFAULT_LABEL_COLORS.get(key, "").upper():
            delta[key] = value
    return delta


def parse_labels(text: str) -> Dict[str, str]:
    """Parse ``.yoke/labels`` text into ``key -> hex``.

    Format is ``label_color_*=HEX`` lines; ``#`` starts a comment (whole-line or
    trailing); values may be single/double quoted.
    """
    values: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = raw_value.split("#", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def read_labels_file(path: "str | object") -> Dict[str, str]:
    """Read + parse a ``.yoke/labels`` file; empty mapping if absent/unreadable."""
    from pathlib import Path

    target = Path(path)
    if not target.is_file():
        return {}
    try:
        return parse_labels(target.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}
