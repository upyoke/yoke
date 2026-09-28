"""Build a corrected QA case beside a failed one and declare it the replacement."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_requirement_replacement import declare_replacements


def corrected_case(conn: Any, *, failed_id: int, case_key: str) -> int:
    """A second case bound to the failed row's exact subject and target."""
    columns = [
        str(row[0])
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='qa_requirements' AND column_name<>'id' "
            "ORDER BY ordinal_position"
        ).fetchall()
    ]
    cleared = {
        "replacement_requirement_id",
        "superseded_by_requirement_id",
        "superseded_at",
        "supersession_rationale",
        "supersession_source",
    }
    projected = [
        "%s" if column == "plan_case_key"
        else "case_position+1" if column == "case_position"
        else "NULL" if column in cleared
        else column
        for column in columns
    ]
    row = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) "
        f"SELECT {','.join(projected)} FROM qa_requirements WHERE id=%s RETURNING id",
        (case_key, int(failed_id)),
    ).fetchone()
    conn.commit()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def requirement_row(conn: Any, requirement_id: int) -> dict[str, Any]:
    return dict(
        conn.execute(
            "SELECT replacement_requirement_id,superseded_by_requirement_id,"
            "supersession_source,supersession_rationale,waived_at "
            "FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
    )


def declare(conn: Any, failed_id: int, case_key: str, produced: list[int]) -> None:
    declare_replacements(
        conn,
        [{"case_key": case_key, "requirement_id": failed_id}],
        materialized_requirement_ids=produced,
    )
    conn.commit()


__all__ = ["corrected_case", "declare", "requirement_row"]
