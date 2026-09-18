"""Names every piece of an item's content and the exact read that returns it.

A detail read answers what an item *is* — its status, workflow, lanes, claim,
and proof. The content itself is a different question: the stored narrative
fields, the body rendered from them, and the Progress Log are large, overlap
each other (the body is a render *of* the fields), and are wanted one piece at
a time. Transferring all of them to answer "what is this item" is the waste
this index removes.

The index is what stays behind. For every piece of content the item actually
holds it reports the size and the command that returns exactly that piece, so
a reader chooses the next read from the answer it already has instead of
taking everything to find out what exists.
"""

from __future__ import annotations

import shlex
from typing import Any, Mapping, Sequence

#: Progress Log is an item section rather than a structured field, so it is
#: read by section name. One spelling, shared with the writer convention.
PROGRESS_LOG_SECTION = "Progress Log"


def _measure(text: str) -> dict[str, int]:
    return {"lines": len(text.splitlines()), "bytes": len(text.encode("utf-8"))}


def _field_read(public_ref: str, field: str) -> str:
    return f"yoke items get {public_ref} {field}"


def build_content_index(
    public_ref: str,
    *,
    narrative: Mapping[str, str],
    progress_log: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Index the content this item holds, each with the read that returns it.

    Empty fields are absent rather than present-and-zero: the index lists what
    is worth reading, and a field holding nothing is not. ``body`` is listed
    whenever any field is, because it is rendered on demand from those fields
    rather than stored, so it has no size to report until it is asked for.
    """
    index: dict[str, dict[str, Any]] = {}
    for field, text in sorted(narrative.items()):
        if field == "body" or not str(text or "").strip():
            continue
        index[field] = {
            **_measure(str(text)),
            "read": _field_read(public_ref, field),
        }
    if index:
        index["body"] = {
            "rendered_on_demand": True,
            "read": _field_read(public_ref, "body"),
        }
    if progress_log:
        content = str(progress_log.get("content") or "")
        index["progress_log"] = {
            **_measure(content),
            "updated_at": progress_log.get("updated_at"),
            "read": (
                f"yoke items section get {public_ref} "
                f"--section {shlex.quote(PROGRESS_LOG_SECTION)}"
            ),
        }
    return index


def instruction_index(
    instructions: Sequence[Mapping[str, Any]],
    *,
    workflow_id: str,
    project_slug: str,
) -> dict[str, Any]:
    """Report how much operator authority applies, and how to read all of it.

    ``count`` is what makes an empty ``execution_instructions`` list readable:
    zero means no instruction governs this item, and non-zero means the bodies
    were not served on this read and ``read`` returns every one of them.
    """
    return {
        "count": len(instructions),
        "bytes": sum(
            len(str(row.get("content") or "").encode("utf-8"))
            for row in instructions
        ),
        "read": (
            "yoke workflow execution-instruction resolve "
            f"--workflow {workflow_id} --project {project_slug} --full"
        ),
    }


__all__ = [
    "PROGRESS_LOG_SECTION",
    "build_content_index",
    "instruction_index",
]
