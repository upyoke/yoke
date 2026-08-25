"""Compact strategy render and ingest responses for CLI output."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from yoke_contracts.project_contract.strategy_docs_paths import (
    strategy_view_rel_path,
)


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") if text.endswith("\n") else text.count("\n") + 1


def _compact_doc(
    doc: Mapping[str, Any], render_report: Mapping[str, str],
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
    return compact


def _render_counts(render_report: Mapping[str, str]) -> Dict[str, int]:
    return {
        "written": sum(
            1 for status in render_report.values() if status == "written"
        ),
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


__all__ = ["compact_file_text_response"]
