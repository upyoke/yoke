"""Turn each vendor's own model listing into the shared availability shape.

Parsing is pure so that the exact bytes a surface produced can be replayed in
a test without that surface installed. The probes that fetch those bytes live
with the relay, which is the only component that runs vendor binaries.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.plan_limits import iso_from_epoch_seconds
from yoke_contracts.session_control.native_models import native_model

CURSOR_LIST_SOURCE = "cursor-agent --list-models"
CODEX_LIST_SOURCE = "codex app-server model/list"

_CURSOR_ROW = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9._-]*)\s+-\s+(.+)$")
#: Cursor encodes reasoning effort into the model token itself, so the token
#: is the selectable identity and the suffix is the published option. Longest
#: first, because "xhigh" also ends with "high".
CURSOR_EFFORT_LEVELS = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "extra-high",
    "max",
)
_CURSOR_EFFORT_SUFFIXES = tuple(sorted(CURSOR_EFFORT_LEVELS, key=len, reverse=True))
#: Cursor's speed variant is a separate token, not a reasoning option.
_CURSOR_SPEED_SUFFIX = "-fast"


def cursor_token_effort(model: str) -> str | None:
    """Name the reasoning effort a Cursor model token encodes, if any."""
    token = (
        str(model or "").removesuffix(_CURSOR_SPEED_SUFFIX).removesuffix("-thinking")
    )
    for effort in _CURSOR_EFFORT_SUFFIXES:
        if token.endswith(f"-{effort}"):
            return effort
    return None


def cursor_selector_without_effort(model: str) -> str:
    """Keep speed/thinking identity while removing a published effort suffix."""
    effort = cursor_token_effort(model)
    if not effort:
        return model
    return re.sub(
        rf"-{re.escape(effort)}(?=(?:-thinking)?(?:{_CURSOR_SPEED_SUFFIX})?$)",
        "",
        model,
    )


def parse_cursor_models(output: str) -> list[dict[str, Any]]:
    """Read Cursor's human ``--list-models`` answer, ignoring its prose lines."""
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in str(output or "").splitlines():
        matched = _CURSOR_ROW.fullmatch(raw.strip())
        if matched is None:
            continue
        token, label = matched.groups()
        if token in seen:
            continue
        seen.add(token)
        effort = cursor_token_effort(token)
        models.append(
            native_model(
                token,
                description=label,
                reasoning_efforts=(effort,) if effort else (),
            )
        )
    return models


def _codex_efforts(raw: Any) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    efforts = []
    for entry in raw:
        effort = entry.get("reasoningEffort") if isinstance(entry, Mapping) else entry
        if isinstance(effort, str) and effort.strip():
            efforts.append(effort.strip())
    return efforts


def _codex_replacement(entry: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Read the vendor's upgrade target and retirement time for one model."""
    info = entry.get("upgradeInfo")
    info = info if isinstance(info, Mapping) else {}
    upgrade = entry.get("upgrade") or info.get("model")
    replaced_by = upgrade.strip() if isinstance(upgrade, str) and upgrade else None
    retirement = info.get("retirementAt")
    retires_at = None
    if replaced_by and isinstance(retirement, (int, float)):
        try:
            retires_at = iso_from_epoch_seconds(retirement)
        except (OSError, OverflowError, ValueError):
            retires_at = None
    return replaced_by, retires_at


def parse_codex_models(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Read one ``model/list`` page, dropping models the app-server hides."""
    data = (payload or {}).get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
        return []
    models: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, Mapping) or entry.get("hidden") is True:
            continue
        token = entry.get("id") or entry.get("model")
        if not isinstance(token, str) or not token.strip():
            continue
        replaced_by, retires_at = _codex_replacement(entry)
        label = entry.get("displayName") or entry.get("description")
        models.append(
            native_model(
                token,
                description=label if isinstance(label, str) else None,
                reasoning_efforts=_codex_efforts(
                    entry.get("supportedReasoningEfforts")
                ),
                default_reasoning_effort=entry.get("defaultReasoningEffort"),
                replaced_by=replaced_by,
                retires_at=retires_at,
            )
        )
    return models


def codex_next_cursor(payload: Mapping[str, Any] | None) -> str | None:
    """Return the cursor for the next ``model/list`` page, if the peer sent one."""
    cursor = (payload or {}).get("nextCursor") if isinstance(payload, Mapping) else None
    return cursor.strip() if isinstance(cursor, str) and cursor.strip() else None


__all__ = [
    "CODEX_LIST_SOURCE",
    "CURSOR_EFFORT_LEVELS",
    "CURSOR_LIST_SOURCE",
    "codex_next_cursor",
    "cursor_token_effort",
    "cursor_selector_without_effort",
    "parse_codex_models",
    "parse_cursor_models",
]
