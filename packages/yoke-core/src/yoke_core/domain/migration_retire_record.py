"""Retire-flow decision-record authoring for governed DB mutations.

For ``mutation_intent = "retire"`` tickets, the implementing phase
authors a decision record per migration module under
``docs/archive/decisions/<identifier>.md``.  The record IS the evidence
the implementing → reviewing-implementation gate
checks for; no rehearsal, lease, audit row, or live apply happens.

This module is the canonical writer.  Skill bodies and operators MUST
route through here so frontmatter shape, module-deletion verification,
and idempotent overwrite all flow through one tested surface — instead
of operators hand-rolling the YAML each time and silently drifting.

CLI usage::

    python3 -m yoke_core.domain.migration_retire_record \\
        --project yoke \\
        --module add_items_due_date \\
        --model primary \\
        --reason "Module never applied; superseded by inline backfill in N."

The CLI resolves this machine's mapped checkout for the project, then
writes ``<checkout>/docs/archive/decisions/<module>.md``.  When the file
already exists with matching ``retired-without-apply: true`` frontmatter
for the same module + model, the helper is a no-op (returns
``unchanged=True`` in JSON) — re-running after the operator has tweaked
the body prose stays safe.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from yoke_core.domain.db_helpers import connect, iso8601_now, query_scalar
from yoke_core.domain.db_mutation_gate_evidence import (
    _parse_yaml_frontmatter,
    decision_record_path,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_checkout_locations import checkout_for_project


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class RetireRecordError(Exception):
    """Raised when retire-record authoring cannot proceed."""


def _resolve_repo_path(project: str, db_path: Optional[str] = None) -> Path:
    conn = connect(db_path)
    try:
        project_id = resolve_project_id(conn, project)
        raw = checkout_for_project(conn, str(project_id))
    finally:
        conn.close()
    if not raw:
        raise RetireRecordError(
            f"project '{project}' has no machine-local checkout mapping"
        )
    return Path(raw)


def _format_record(
    *,
    module: str,
    model: str,
    reason: str,
    retired_at: str,
    body: str = "",
) -> str:
    """Compose a retire decision record.

    Frontmatter ordering matches the gate's parsed expectations
    (db_mutation_gate._verify_retire_record).  Body defaults to a
    non-empty justification skeleton when the caller didn't supply one
    so the file isn't structurally empty after frontmatter.
    """
    body_text = body.strip() or (
        f"Module `{module}` was retired without ever being applied to the "
        f"`{model}` authoritative DB.\n\n"
        f"## Why retire instead of apply?\n\n{reason}\n"
    )
    frontmatter = (
        "---\n"
        f"retired-without-apply: true\n"
        f"migration_module: {module}\n"
        f"model_name: {model}\n"
        f"retired_at: {retired_at}\n"
        f"reason: {reason}\n"
        "---\n\n"
    )
    return frontmatter + body_text + ("\n" if not body_text.endswith("\n") else "")


def _record_matches(
    existing_text: str,
    *,
    module: str,
    model: str,
) -> bool:
    """Return True when an existing record is already a retire record for the
    same module + model (regardless of body / reason wording)."""
    fm = _parse_yaml_frontmatter(existing_text)
    if not fm:
        return False
    if fm.get("retired-without-apply") is not True:
        return False
    if fm.get("migration_module") != module:
        return False
    if fm.get("model_name") != model:
        return False
    return True


def write_retire_record(
    *,
    project: str,
    module: str,
    model: str,
    reason: str,
    body: str = "",
    db_path: Optional[str] = None,
    repo_path: Optional[Path] = None,
    retired_at: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Author a retire decision record for *module* under *project*.

    Returns a result dict::

        {
            "path": "<absolute path to the written file>",
            "wrote": True | False,
            "unchanged": True | False,
            "reason": "...",  # repeated for caller convenience
        }

    When the file already exists with matching frontmatter the helper
    is a no-op (``wrote=False``, ``unchanged=True``) so re-running after
    a manual body edit stays safe.  Pass ``overwrite=True`` to
    rewrite the file even when the frontmatter would have matched.
    """
    if not module or "/" in module or module.endswith(".py"):
        raise RetireRecordError(
            f"module identifier '{module}' must be a bare slug "
            "(no path, no extension)"
        )
    if not str(reason or "").strip():
        raise RetireRecordError("reason must be a non-empty string")

    resolved_repo = repo_path or _resolve_repo_path(project, db_path)
    target = decision_record_path(resolved_repo, module)
    target.parent.mkdir(parents=True, exist_ok=True)

    timestamp = retired_at or iso8601_now()
    rendered = _format_record(
        module=module, model=model, reason=reason,
        retired_at=timestamp, body=body,
    )

    if target.is_file() and not overwrite:
        existing = target.read_text(encoding="utf-8")
        if _record_matches(existing, module=module, model=model):
            return {
                "path": str(target),
                "wrote": False,
                "unchanged": True,
                "reason": reason,
            }

    target.write_text(rendered, encoding="utf-8")
    return {
        "path": str(target),
        "wrote": True,
        "unchanged": False,
        "reason": reason,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migration_retire_record",
        description=(
            "Author a retire decision record under "
            "docs/archive/decisions/<module>.md for a "
            "mutation_intent='retire' migration ticket."
        ),
    )
    parser.add_argument("--project", required=True,
                        help="Project id the migration model belongs to.")
    parser.add_argument("--module", required=True,
                        help="Migration module identifier (slug, no extension).")
    parser.add_argument("--model", required=True,
                        help="Model name from the project's migration_model "
                             "capability (e.g. 'primary').")
    parser.add_argument("--reason", required=True,
                        help="Non-empty justification persisted to the "
                             "frontmatter and body.")
    parser.add_argument("--body", default="",
                        help="Optional pre-composed body content. "
                             "Defaults to a generated skeleton.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Force-rewrite even if the existing record "
                             "already has matching frontmatter.")
    parser.add_argument("--retired-at", default=None,
                        help="UTC ISO-8601 timestamp; defaults to now.")

    args = parser.parse_args(argv)

    try:
        result = write_retire_record(
            project=args.project,
            module=args.module,
            model=args.model,
            reason=args.reason,
            body=args.body,
            retired_at=args.retired_at,
            overwrite=args.overwrite,
        )
    except RetireRecordError as exc:
        print(json.dumps({"success": False, "error": str(exc)}),
              file=sys.stderr)
        return 1

    print(json.dumps({"success": True, **result}))
    return 0


__all__ = [
    "RetireRecordError",
    "write_retire_record",
]


if __name__ == "__main__":
    sys.exit(main())
