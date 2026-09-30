"""Compact strategy render and ingest responses for CLI output."""

from __future__ import annotations

import sys
from typing import Any, Dict, Mapping, Optional

from yoke_cli.commands.adapters.strategy import write_rendered_files
from yoke_cli.commands.adapters.strategy_target_project import (
    resolve_and_validate_target_root,
    StrategyTargetRootMismatchError,
)

from yoke_contracts.project_contract.strategy_docs_paths import (
    strategy_view_rel_path,
)


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") if text.endswith("\n") else text.count("\n") + 1


def _compact_doc(
    doc: Mapping[str, Any],
    render_report: Mapping[str, str],
) -> Dict[str, Any]:
    compact = dict(doc)
    file_text = compact.pop("file_text", None)
    slug = str(compact.get("slug") or "")
    archived = bool(compact.get("archived", False))
    if slug:
        compact["path"] = strategy_view_rel_path(slug, archived=archived)
        if slug in render_report:
            compact["render_status"] = render_report[slug]
    if isinstance(file_text, str):
        compact["file_bytes"] = len(file_text.encode("utf-8"))
        compact["file_lines"] = _line_count(file_text)
    elif compact.get("bytes") is not None:
        compact["file_bytes"] = int(compact["bytes"])
    return compact


def _render_counts(render_report: Mapping[str, str]) -> Dict[str, int]:
    return {
        "written": sum(1 for status in render_report.values() if status == "written"),
        "unchanged": sum(
            1 for status in render_report.values() if status == "unchanged"
        ),
    }


def compact_file_text_response(
    response,
    *,
    target_root,
    render_report: Optional[Mapping[str, str]],
):
    """Return a CLI-facing response with file bodies replaced by metadata."""
    report = dict(render_report or {})
    result = dict(response.result or {})
    docs = result.get("docs")
    if isinstance(docs, list):
        result["docs"] = [
            _compact_doc(doc, report) if isinstance(doc, Mapping) else doc
            for doc in docs
        ]
    result["target_root"] = str(target_root)
    if report:
        result["rendered"] = _render_counts(report)
    return response.model_copy(update={"result": result})


def _write_returned_files(
    target_root,
    response,
    *,
    explicit_target_root: bool = True,
) -> Dict[str, str]:
    """Write any ``file_text`` entries the ingest response carries.

    The written docs already landed in the DB by the time this runs, so a
    project mismatch on ``target_root`` warns and skips the local
    header-advance write rather than unwinding anything.
    """
    result = (response.result or {}) if response else {}
    docs = result.get("docs", [])
    entries = [d for d in docs if d.get("file_text")]
    if not entries:
        return {}
    try:
        target_root = resolve_and_validate_target_root(
            target_root,
            explicit=explicit_target_root,
            project_id=result.get("project_id"),
            project_slug=result.get("project_slug"),
        )
    except StrategyTargetRootMismatchError as exc:
        print(
            "warning: strategy doc(s) ingested in the DB; skipped local "
            f"header refresh — {exc}",
            file=sys.stderr,
        )
        return {}
    return write_rendered_files(target_root, entries)


__all__ = ["compact_file_text_response", "_write_returned_files"]
