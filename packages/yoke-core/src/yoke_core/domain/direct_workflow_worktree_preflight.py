"""Engine-owned worktree preparation for Dash and Blitz execution."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import sys
from typing import Iterator, List, Optional

from yoke_core.domain.conflict_survey import (
    read_recorded_survey,
    survey_conflicts,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity_item_ref import resolve_cli_item_ref
from yoke_core.domain.worktree_preflight import run_preflight


@contextmanager
def _session_identity(session_id: str) -> Iterator[None]:
    previous = os.environ.get("YOKE_SESSION_ID")
    if session_id:
        os.environ["YOKE_SESSION_ID"] = session_id
    try:
        yield
    finally:
        if session_id:
            if previous is None:
                os.environ.pop("YOKE_SESSION_ID", None)
            else:
                os.environ["YOKE_SESSION_ID"] = previous


def run(args: List[str]) -> int:
    """Validate the recorded survey, then prepare the ordinary item lane."""
    parser = argparse.ArgumentParser(
        prog="yoke direct-workflow worktree prepare",
    )
    parser.add_argument("item")
    parser.add_argument("--workflow", choices=("dash", "blitz"), required=True)
    parser.add_argument("--project")
    parser.add_argument(
        "--session-id",
        default=os.environ.get("YOKE_SESSION_ID", ""),
    )
    parsed = parser.parse_args(args)

    with connect() as conn:
        item_id = resolve_cli_item_ref(
            conn,
            parsed.item,
            project_context=parsed.project,
        )
        if item_id is None:
            parser.error(f"could not resolve item {parsed.item!r}")
        row = conn.execute(
            "SELECT workflow_id FROM items WHERE id = %s",
            (item_id,),
        ).fetchone()
        if row is None or str(row[0]) != parsed.workflow:
            actual = str(row[0]) if row else "missing"
            parser.error(
                f"item uses workflow {actual!r}, not {parsed.workflow!r}"
            )
        recorded = read_recorded_survey(conn, int(item_id))
        if not recorded:
            print(json.dumps({
                "ok": False,
                "block_kind": "conflict-survey-missing",
                "narrative": (
                    "Record the inferred touch set before worktree preparation."
                ),
                "item_id": int(item_id),
            }))
            return 1
        live = survey_conflicts(
            conn,
            item_id=int(item_id),
            touch_paths=recorded.get("touch_paths") or (),
            integration_target=str(
                recorded.get("integration_target") or "main"
            ),
        )
        if not live.clear:
            print(json.dumps({
                "ok": False,
                "block_kind": "conflict-survey-blocked",
                "narrative": (
                    "Registered coordination wins over claim-less work."
                ),
                "item_id": int(item_id),
                "blockers": [
                    {
                        "kind": blocker.kind,
                        "owner_item_id": blocker.owner_item_id,
                        "path": blocker.path,
                        "state": blocker.state,
                        "detail": blocker.detail,
                    }
                    for blocker in live.blockers
                ],
            }))
            return 1

    with _session_identity(parsed.session_id):
        outcome = run_preflight(
            item_id=int(item_id),
            project=parsed.project,
            session_id=parsed.session_id,
            actual_cwd=os.getcwd(),
        )
    print(json.dumps(outcome.to_envelope(), indent=2, sort_keys=True))
    return 0 if outcome.ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
