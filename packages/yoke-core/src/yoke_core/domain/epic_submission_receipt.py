"""Submission receipt parsing and lookup for epic task progress notes."""

from __future__ import annotations

import re
from typing import Any, Mapping

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.epic_parsing import _placeholder

SUBMISSION_START = "---SUBMISSION-CHECKS-START---"
SUBMISSION_END = "---SUBMISSION-CHECKS-END---"

REQUIRED_KEYS = (
    "test_plan",
    "files_touched",
    "edited_tests",
    "clean_worktree",
    "progress_notes",
    "file_budget",
)

_STATUS_RE = re.compile(r"^\s*([A-Za-z_]+)")


def _status(value: str) -> str:
    match = _STATUS_RE.match(value or "")
    return match.group(1).upper() if match else ""


def extract_submission_block(body: str) -> str:
    """Return the final submission-checks block body from *body*.

    Progress notes may contain ordinary narrative plus the receipt block. The
    final block wins so remediation notes can supersede earlier text.
    """
    text = body or ""
    start = text.rfind(SUBMISSION_START)
    if start < 0:
        raise LookupError("missing submission receipt block")
    start += len(SUBMISSION_START)
    end = text.find(SUBMISSION_END, start)
    if end < 0:
        raise LookupError("missing submission receipt end delimiter")
    return text[start:end].strip()


def parse_submission_fields(body: str) -> dict[str, str]:
    """Parse key/value lines from a submission receipt block."""
    block = extract_submission_block(body)
    fields: dict[str, str] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def validate_submission_fields(fields: Mapping[str, str]) -> None:
    """Raise ``ValueError`` when a receipt is missing or failing fields."""
    missing = [key for key in REQUIRED_KEYS if key not in fields]
    if missing:
        raise ValueError("submission receipt missing field(s): " + ", ".join(missing))

    allowed = {"PASS", "SKIP"}
    for key in ("test_plan", "files_touched", "edited_tests", "progress_notes", "file_budget"):
        status = _status(fields[key])
        if status not in allowed:
            raise ValueError(f"submission receipt field {key} is {status or 'malformed'}")

    clean = _status(fields["clean_worktree"])
    if clean != "PASS":
        raise ValueError(f"submission receipt field clean_worktree is {clean or 'malformed'}")


def format_submission_fields(fields: Mapping[str, str]) -> str:
    """Render fields in canonical order for operator-readable CLI output."""
    return "; ".join(f"{key}={fields[key]}" for key in REQUIRED_KEYS)


def submission_receipt_get(
    conn: Any,
    epic_id: str,
    task_num: int,
    *,
    after_note_count: int = 0,
) -> str:
    """Return the latest valid receipt after *after_note_count*.

    The lookup deliberately reads ``epic_progress_notes`` instead of any Agent
    result text. This gives conduct a durable receipt surface that survives
    Agent-result summarization and transcript truncation.
    """
    p = _placeholder(conn)
    rows = query_rows(
        conn,
        f"""
        SELECT note_num, COALESCE(commit_hash, '') AS commit_hash,
               COALESCE(created_at, '') AS created_at, COALESCE(body, '') AS body
        FROM epic_progress_notes
        WHERE epic_id = {p}
          AND task_num = {p}
          AND note_num > {p}
          AND body LIKE {p}
        ORDER BY note_num DESC, created_at DESC
        """,
        (str(epic_id), task_num, after_note_count, f"%{SUBMISSION_START}%"),
    )
    if not rows:
        raise LookupError(
            f"no submission receipt found for {epic_id}/{task_num} after note {after_note_count}"
        )

    row = rows[0]
    fields = parse_submission_fields(row["body"])
    validate_submission_fields(fields)
    return (
        f"PASS|{epic_id}|{task_num}|{row['note_num']}|"
        f"{row['commit_hash']}|{row['created_at']}|{format_submission_fields(fields)}"
    )
