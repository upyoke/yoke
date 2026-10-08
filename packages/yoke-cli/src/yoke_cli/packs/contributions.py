"""Explicit Pack-owned blocks in canonical guidance and ignore files.

The immutable source contains only one marked contribution. Its digest stays
the receipt baseline; the planner writes a composed file without claiming the
project's surrounding bytes. No other target opts into file composition.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Mapping

from yoke_contracts.project_contract.managed_block import (
    MANAGED_BLOCK_BEGIN,
    MANAGED_BLOCK_END,
    block_span,
)

_TARGETS = {"AGENTS.md": ("<!-- ", " -->"), ".gitignore": ("# ", "")}
_SLUG = r"[a-z][a-z0-9-]*"


def contribution_markers(entry: Mapping[str, Any]) -> tuple[str, str] | None:
    """Recognize an explicit, bounded contribution, refusing malformed source."""
    path = entry["path"]
    content = entry["content"]
    if path not in _TARGETS or "YOKE PACK" not in content:
        return None
    prefix, suffix = _TARGETS[path]
    match = re.match(
        re.escape(prefix) + r"BEGIN YOKE PACK (" + _SLUG + r")" + re.escape(suffix),
        content,
    )
    if match is None or entry.get("encoding", "utf-8") != "utf-8":
        raise ValueError("malformed_pack_contribution")
    slug = match.group(1)
    begin = f"{prefix}BEGIN YOKE PACK {slug}{suffix}"
    end = f"{prefix}END YOKE PACK {slug}{suffix}"
    span = _span(content, begin, end)
    if span is None or content[: span[0]] or content[span[1] :] not in {"", "\n"}:
        raise ValueError("malformed_pack_contribution")
    if MANAGED_BLOCK_BEGIN in content or MANAGED_BLOCK_END in content:
        raise ValueError("pack_contribution_inside_project_block")
    return begin, end


def _span(text: str, begin: str, end: str) -> tuple[int, int] | None:
    if begin not in text and end not in text:
        return None
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError("malformed_pack_contribution")
    span = block_span(text, begin, end)
    if span is None:
        raise ValueError("malformed_pack_contribution")
    start, finish = span
    if (
        (start and text[start - 1] != "\n")
        or (finish < len(text) and text[finish] not in "\r\n")
        or text[start + len(begin) : start + len(begin) + 1] != "\n"
    ):
        raise ValueError("malformed_pack_contribution")
    inner = text[start + len(begin) : finish - len(end)]
    if not inner.endswith("\n") or "YOKE PACK" in inner:
        raise ValueError("malformed_pack_contribution")
    return span


def compose_contribution(
    wanted: Mapping[str, Any],
    current: Mapping[str, Any] | None,
    prior: Mapping[str, Any] | None,
    merge: Callable[[str, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a write/unchanged/retained/conflict outcome, or ordinary-file None."""
    try:
        markers = contribution_markers(wanted)
        if markers is None:
            return None
        begin, end = markers
        incoming = wanted["content"].rstrip("\n")
        if current is None:
            if prior is not None and prior["sha256"] == wanted["sha256"]:
                return {
                    "kind": "retained",
                    "reason": "project_removed_unchanged_upstream",
                }
            if prior is not None:
                raise ValueError("upstream_changed_project_removed_contribution")
            text = ""
        else:
            if current["encoding"] != "utf-8":
                raise ValueError("binary_contribution_target")
            text = current["content"]
        span = _span(text, begin, end)
        yoke_span = block_span(text)
        if (MANAGED_BLOCK_BEGIN in text or MANAGED_BLOCK_END in text) and (
            yoke_span is None
            or text.count(MANAGED_BLOCK_BEGIN) != 1
            or text.count(MANAGED_BLOCK_END) != 1
        ):
            raise ValueError("malformed_project_managed_block")
        if span and yoke_span and span[0] < yoke_span[1] and span[1] > yoke_span[0]:
            raise ValueError("pack_contribution_inside_project_block")
        if span:
            owned = text[span[0] : span[1]]
            if prior is None:
                if owned != incoming:
                    raise ValueError("existing_pack_contribution")
            elif contribution_markers(prior) == markers:
                result = merge(owned, prior["content"].rstrip("\n"), incoming)
                if result["conflicted"]:
                    raise ValueError("overlapping_contribution_customization")
                incoming = result["content"].rstrip("\n")
                _span(incoming, begin, end)
            elif contribution_markers(prior) is None and owned == incoming:
                # Explicit reconciliation of a previous whole-file baseline
                # must retain both project notes and install-owned doctrine.
                pass
            else:
                raise ValueError("contribution_ownership_changed")
            composed = text[: span[0]] + incoming + text[span[1] :]
        else:
            if prior is not None and contribution_markers(prior) is not None:
                if prior["sha256"] == wanted["sha256"]:
                    return {
                        "kind": "retained",
                        "reason": "project_removed_unchanged_upstream",
                    }
                raise ValueError("upstream_changed_project_removed_contribution")
            if prior is not None and current is not None:
                # Retire a previous whole-file baseline through the existing
                # three-way merge; customized old doctrine cannot be erased.
                result = merge(text, prior["content"], "")
                if result["conflicted"]:
                    raise ValueError("whole_file_to_contribution_conflict")
                text = result["content"]
            separator = "" if not text or text.endswith("\n") else "\n"
            composed = text + separator + incoming + "\n"
        if current is not None and composed == current["content"]:
            return {"kind": "unchanged"}
        return {
            "kind": "create" if current is None else "update",
            "write": {
                "path": wanted["path"],
                "content": composed,
                "encoding": "utf-8",
                "mode": current["mode"] if current is not None else wanted["mode"],
                "sha256": hashlib.sha256(composed.encode("utf-8")).hexdigest(),
            },
        }
    except ValueError as exc:
        return {
            "kind": "conflict",
            "reason": str(exc),
            "recovery": "Repair the named Pack boundaries outside the Yoke managed block; preserve project content, then preview again. For an old whole-file baseline, reconcile scaffold guidance into application docs and install the exact incoming marked contribution outside the Yoke block, keeping project notes, then retry update.",
        }
