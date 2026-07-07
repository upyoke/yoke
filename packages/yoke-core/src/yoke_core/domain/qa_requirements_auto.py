"""Auto-create basic QA requirements for non-browser issue tickets."""

from __future__ import annotations

import json
import re
from typing import Optional

from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.qa_events import emit_qa_requirement_event

PYTEST_TARGET = "python3 -m yoke_core.tools.watch_pytest -- runtime/api/"


def _browser_section(spec: str) -> Optional[str]:
    match = re.search(
        r"^## Browser QA Metadata\s*(.*?)(?=^## |\Z)",
        spec,
        flags=re.M | re.S,
    )
    return match.group(1) if match else None


def _parsed_metadata(row: dict) -> Optional[dict]:
    raw = row.get("browser_qa_metadata")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _metadata_is_browser_testable(row: dict) -> bool:
    data = _parsed_metadata(row)
    return bool(data.get("browser_testable")) if data else False


def _metadata_says_not_browser_testable(row: dict) -> bool:
    """True only when the stored ``browser_qa_metadata`` object explicitly
    classifies the item as non-browser (``browser_testable`` present and false).

    Distinct from ``_metadata_is_browser_testable`` returning ``False``, which
    also covers the no-metadata / unparseable cases. This is the authoritative
    "confirmed non-browser" signal.
    """
    data = _parsed_metadata(row)
    return data is not None and "browser_testable" in data and not data["browser_testable"]


def _should_create(row: dict) -> bool:
    if str(row.get("type") or "") != "issue":
        return False
    if _metadata_is_browser_testable(row):
        return False
    # The authoritative browser_qa_metadata object is the source of truth for the
    # non-browser classification. When it explicitly records browser_testable=false,
    # seed regardless of section-prose wording: standard phrasings like
    # "Non-browser ticket: ..." match none of the prose heuristics below and would
    # otherwise leave the verification-entry gate with zero requirements.
    if _metadata_says_not_browser_testable(row):
        return True
    section = _browser_section(str(row.get("spec") or ""))
    if section is None:
        return True
    lowered = section.lower()
    if "not browser-testable" in lowered or "browser_testable: false" in lowered:
        return True
    if "browser_testable: true" in lowered or "browser-testable" in lowered:
        return False
    return False


def _ac_list(spec: str) -> str:
    acs = []
    for line in spec.splitlines():
        match = re.match(r"^- \[ \] (AC-\d+:\s*.*)$", line.strip())
        if match:
            acs.append(match.group(1).strip())
    return "; ".join(acs) if acs else "none listed"


def _existing_requirement(conn, item_id: int) -> Optional[int]:
    row = conn.execute(
        """SELECT id FROM qa_requirements
           WHERE item_id=%s AND qa_kind='ac_verification'
           AND qa_phase='verification' AND waived_at IS NULL
           ORDER BY id LIMIT 1""",
        (item_id,),
    ).fetchone()
    return int(row["id"]) if row else None


def auto_create_for_item(
    item_id: int,
    *,
    dry_run: bool = False,
    db_path: Optional[str] = None,
) -> Optional[int]:
    """Create one blocking AC verification requirement when appropriate."""
    conn = connect(path=db_path)
    try:
        existing = _existing_requirement(conn, item_id)
        if existing is not None:
            return existing
        row = conn.execute("SELECT * FROM items WHERE id=%s", (item_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        if not _should_create(item):
            return None
        if dry_run:
            return None
        policy = f"pytest target: {PYTEST_TARGET}; AC list: {_ac_list(item.get('spec') or '')}"
        cur = conn.execute(
            """INSERT INTO qa_requirements
               (item_id, qa_kind, qa_phase, blocking_mode,
                requirement_source, success_policy, created_at)
               VALUES (%s, 'ac_verification', 'verification', 'blocking',
                       'ac_derived', %s, %s) RETURNING id""",
            (item_id, policy, iso8601_now()),
        )
        req_id = int(cur.fetchone()[0])
        # QA requirement writes are real item activity (R1 semantics).
        from yoke_core.domain.item_activity import touch_item_activity
        touch_item_activity(conn, item_id=item_id)
        conn.commit()
        emit_qa_requirement_event(
            conn,
            db_path=db_path,
            event_name="QARequirementCreated",
            requirement_id=req_id,
            qa_kind="ac_verification",
            qa_phase="verification",
            target_row={"item_id": item_id, "epic_id": None, "task_num": None,
                        "deployment_run_id": None},
            extra_detail={"source": "auto_non_browser"},
        )
        return req_id
    finally:
        conn.close()


__all__ = ["PYTEST_TARGET", "auto_create_for_item"]
