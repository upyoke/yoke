"""Backlog GitHub sync CLI dispatcher."""

from __future__ import annotations

import re
import sys
from typing import Any, Iterable, Optional, TextIO

from yoke_core.domain.backlog_github_sync_accessor import bgs as _bgs
from yoke_core.domain import backlog_github_body_budget as _budget, db_backend
from yoke_core.domain.backlog_github_fetch import (
    _close_if_owned,
    _item_context,
    _item_ref,
    _open_conn,
)
from yoke_core.domain.backlog_github_transport import _dry_run
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)
from yoke_core.domain.render_body import build_body
from yoke_core.domain.yok_n_parser import parse_item_id


_MUTATING_MODES = {
    "frozen-label": ("sync_frozen_label", "sync frozen label", 2),
    "blocked-label": ("sync_blocked_label", "sync blocked label", 2),
    "sync-labels": ("sync_labels", "sync labels", 1),
    "sync-item": ("sync_item", "sync item", 1),
    "post-comment": ("post_comment", "post comment", 3),
    "close-issue": ("close_issue", "close issue", 1),
    "reopen-issue": ("reopen_issue", "reopen issue", 1),
    "sync-body": ("sync_body", "sync body", 1),
    "sync-title": ("sync_title", "sync title", 1),
    "migrate-issue": ("migrate_issue_to_repo", "migrate issue", 6),
}


USAGE = """\
Usage: python3 -m yoke_core.domain.backlog_github_sync <mode> [args...]

Modes:
  update-repo-labels [--dry-run]
  frozen-label <item-id> <true|false>
  blocked-label <item-id> <true|false>
  sync-labels <item-id>
  sync-item <item-id>
  post-comment <item-id> <old-status> <new-status>
  close-issue <item-id>
  reopen-issue <item-id>
  sync-body <item-id>
  sync-title <item-id>
  backfill-oversized-bodies
  migrate-issue <item-id> <old-issue> <source-repo> <source-project> <target-repo> <target-project>
"""


def _resolve_session_id() -> str:
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    return resolve_ambient_session_id() or ""


def _normalize_item_id(raw: str, *, conn: Optional[Any] = None) -> Optional[int]:
    try:
        return parse_item_id(raw, conn=conn, allow_bare_internal=True)
    except ValueError:
        match = re.match(r"^[A-Za-z][A-Za-z0-9]*-0*(\d+)$", str(raw).strip())
        if match:
            return int(match.group(1))
        return None


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def check_ownership(
    item_id_raw: str,
    *,
    conn: Optional[Any] = None,
    session_id: Optional[str] = None,
) -> tuple[bool, str, str]:
    """Return ``(allow, reason, holder_session_id)`` for item mutation."""
    if _dry_run():
        return True, "dry-run", ""

    session_id = session_id if session_id is not None else _resolve_session_id()

    own_conn = False
    try:
        if conn is None:
            try:
                conn, own_conn = _open_conn(None)
            except FileNotFoundError:
                return True, "no-db", ""
        item_id = _normalize_item_id(item_id_raw, conn=conn)
        if item_id is None:
            return True, "unparseable-item-id", ""
        p = _p(conn)
        try:
            row = conn.execute(
                "SELECT wc.session_id, hs.ended_at FROM work_claims wc "
                "LEFT JOIN harness_sessions hs ON hs.session_id = wc.session_id "
                f"WHERE wc.target_kind = 'item' AND wc.item_id = {p} "
                "AND wc.released_at IS NULL "
                "ORDER BY claimed_at DESC LIMIT 1",
                (int(item_id),),
            ).fetchone()
        except db_backend.operational_error_types(conn):
            conn.rollback()
            return True, "no-claims-table", ""
    finally:
        if own_conn and conn is not None:
            _close_if_owned(conn, True)

    if row is None:
        return True, "no-claim", ""

    holder = row[0] if not hasattr(row, "keys") else row["session_id"]
    holder = holder or ""
    if not holder:
        return True, "claim-without-session", ""
    ended_at = row[1] if not hasattr(row, "keys") else row["ended_at"]
    if ended_at:
        return True, "holder-ended", holder
    if session_id and holder == session_id:
        return True, "self-owned", holder
    return False, "other-holder", holder


def _guard_or_print(item_id_raw: str, mode_label: str) -> int:
    allow, reason, holder = check_ownership(item_id_raw)
    if allow:
        return 0
    print(
        f"Refusing to {mode_label} for item {item_id_raw}: "
        f"work claim held by session {holder}",
        file=sys.stderr,
    )
    return 1


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(USAGE, file=sys.stderr)
        return 1
    if args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    mode = args[0]
    rest = args[1:]

    if mode == "update-repo-labels":
        if not rest:
            return _bgs().update_repo_labels()
        if rest == ["--dry-run"]:
            return _bgs().update_repo_labels(dry_run=True)
        print(USAGE, file=sys.stderr)
        return 1
    if mode == "backfill-oversized-bodies" and not rest:
        return backfill_oversized_bodies()
    if mode in _MUTATING_MODES:
        func_name, label, argc = _MUTATING_MODES[mode]
        if len(rest) != argc:
            print(USAGE, file=sys.stderr)
            return 1
        rc = _guard_or_print(rest[0], label)
        if rc:
            return rc
        return getattr(_bgs(), func_name)(*rest)
    print(USAGE, file=sys.stderr)
    return 1


def _select_compact_pending_candidates(conn: Any) -> list[int]:
    """Items whose GitHub mirror is currently the compact fallback.

    Reads the ``items.github_body_compact_pending`` flag — item-side
    sync state stamped by the body-sync paths. The retired pattern was
    inferring this work queue from body-too-long markers in
    ``HarnessToolCallCompleted`` telemetry envelopes.
    """
    return _budget.list_compact_pending_item_ids(conn)


def _select_oversized_current_candidates(
    conn: Any,
) -> Iterable[tuple[int, int]]:
    rows = conn.execute(
        "SELECT id FROM items "
        "WHERE github_issue IS NOT NULL AND github_issue <> '' ORDER BY id"
    ).fetchall()
    for row in rows:
        item_id = int(row[0]) if not hasattr(row, "keys") else int(row["id"])
        body = build_body(conn, item_id) or ""
        if _budget.body_exceeds_budget(body):
            yield item_id, len(body.encode("utf-8"))

def backfill_oversized_bodies(
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Repair oversized bodies and compact-pending mirror candidates.

    Candidates are the union of items whose rendered body currently
    exceeds the budget (sync lands the compact mirror) and items
    flagged ``github_body_compact_pending`` (sync restores the full
    body when it fits again and clears the flag — ``sync_body`` owns
    the flag transition either way).
    """
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    try:
        conn, owns_conn = _open_conn(conn)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=stderr)
        return 1

    try:
        oversized = dict(_select_oversized_current_candidates(conn))
        flag_derived = _select_compact_pending_candidates(conn)
        flag_only = [iid for iid in flag_derived if iid not in oversized]
        scanned = len(oversized) + len(flag_only)
        repaired = 0
        restored = 0
        auth_failures = 0
        sync_failures = 0
        skipped_claimed = 0

        candidates = [
            (item_id, oversized.get(item_id))
            for item_id in sorted(set(oversized) | set(flag_only))
        ]
        for item_id, body_bytes in candidates:
            item_ref = _item_ref(item_id, conn=conn)
            allow, _reason, holder = check_ownership(str(item_id), conn=conn)
            if not allow:
                skipped_claimed += 1
                print(
                    f"Skipped: {item_ref} skipped_claimed "
                    f"(held by session {holder})",
                    file=stderr,
                )
                continue

            # Auth precedence. Catch typed errors per-item and log.
            context = _item_context(str(item_id), conn=conn)
            project = (context[1] if context else "") or "yoke"
            try:
                resolve_project_github_auth(project)
            except ProjectGithubAuthError as exc:
                auth_failures += 1
                print(
                    f"Skipped: {item_ref} auth failure: "
                    f"{type(exc).__name__}: {exc}",
                    file=stderr,
                )
                continue

            rc = _bgs().sync_body(str(item_id), conn=conn, stderr=stderr)
            if rc != 0:
                sync_failures += 1
                print(
                    f"Failed: {item_ref} sync_body returned {rc}",
                    file=stderr,
                )
                continue

            if body_bytes is not None:
                repaired += 1
                source = (
                    "flag+oversized" if item_id in flag_derived
                    else "oversized"
                )
                print(
                    f"Backfilled: {item_ref} → compact mirror "
                    f"(was {body_bytes} bytes, source={source})",
                    file=stdout,
                )
            else:
                restored += 1
                print(
                    f"Restored: {item_ref} → full body "
                    "(fits under budget again, source=flag)",
                    file=stdout,
                )

        print(
            f"Total: {repaired} items repaired, {restored} restored "
            f"(scanned {scanned}, flag-derived {len(flag_derived)}, "
            f"oversized-current {len(oversized)}, "
            f"auth failures {auth_failures}, "
            f"sync failures {sync_failures}, "
            f"skipped_claimed {skipped_claimed})",
            file=stdout,
        )
        return 1 if (auth_failures or sync_failures) else 0
    finally:
        _close_if_owned(conn, owns_conn)


__all__ = [
    "main",
    "USAGE",
    "backfill_oversized_bodies",
    "check_ownership",
    "_select_compact_pending_candidates",
    "_select_oversized_current_candidates",
]
