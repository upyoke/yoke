"""Parent-epic status derivation from aggregate task states.

When a task transitions, recompute the parent epic's item status from the
aggregate task state distribution.  Writes route through the canonical
in-process backlog mutator (``yoke_core.domain.backlog.execute_update``),
honoring the ``auto-derive`` claim bypass and the ``YOKE_QA_GATE_BYPASS``
escape hatch.  All warnings are surfaced on the supplied stderr stream.
"""

from __future__ import annotations

import io as _io
import os
import sys
from typing import Any, Optional, TextIO

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.lifecycle import TASK_TERMINAL_SUCCESS, TERMINAL_FAILURE


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def auto_derive_epic_status(
    conn: Any,
    epic_id: str,
    new_status: str,
    *,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> None:
    """Recompute parent epic status from aggregate task states."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    p = _p(conn)

    rows = query_rows(
        conn,
        f"SELECT task_num, status FROM epic_tasks WHERE epic_id={p}",
        (str(epic_id),),
    )
    if not rows:
        return

    total = len(rows)
    in_flight = 0
    terminal_success = 0
    terminal_failure = 0
    pre_execution_ready = 0
    blocked = 0

    for row in rows:
        st = row["status"]
        if st in ("implementing", "reviewing-implementation"):
            in_flight += 1
        elif st in TASK_TERMINAL_SUCCESS:
            terminal_success += 1
        elif st in TERMINAL_FAILURE:
            terminal_failure += 1
        elif st in ("planning", "planned"):
            pre_execution_ready += 1
        elif st == "blocked":
            blocked += 1

    # Derive target status
    derived = None
    if in_flight > 0:
        derived = "implementing"
    elif terminal_success == total:
        derived = "reviewing-implementation"
    elif terminal_failure > 0 and terminal_success > 0:
        derived = "implementing"
    elif pre_execution_ready == total:
        derived = "planned"
    elif pre_execution_ready > 0 and (pre_execution_ready + blocked) == total:
        derived = "planned"

    parent_status = query_scalar(
        conn,
        f"SELECT status FROM items WHERE CAST(id AS TEXT)=CAST({p} AS TEXT)",
        (str(epic_id),),
    )

    # A parent epic already at ``release`` never derives backward to an earlier
    # status.  Instead, when every child task is exactly ``done``, finalize it
    # through the done-transition engine so the engine's preconditions,
    # merge/deploy/recovery gates, GitHub sync, board rebuild, and scoped
    # ``YOKE_CLAIM_BYPASS`` stay authoritative -- auto-derive never writes
    # ``items.status='done'`` directly.
    if parent_status == "release":
        _finalize_release_epic_if_ready(
            conn, epic_id, rows, stdout=stdout, stderr=stderr
        )
        return

    if derived is None:
        return

    # Guard: only override certain parent statuses
    if parent_status not in ("planned", "implementing", "reviewing-implementation", "reviewed-implementation"):
        return

    if parent_status == derived:
        return

    print(f"Auto-deriving epic YOK-{epic_id} status: {parent_status} -> {derived}", file=stdout)

    # direct in-process call to the owned backlog domain.
    from yoke_core.domain import backlog

    try:
        epic_id_int = int(epic_id)
    except (TypeError, ValueError):
        print(
            f"WARNING: auto_derive_epic_status: cannot coerce epic id '{epic_id}' to int",
            file=stderr,
        )
        return

    env_overrides = {
        "YOKE_CLAIM_BYPASS": f"auto-derive:epic-{epic_id}",
        "YOKE_STATUS_SOURCE": "auto-derive",
    }
    previous_env: dict[str, Optional[str]] = {}
    for key, val in env_overrides.items():
        previous_env[key] = os.environ.get(key)
        os.environ[key] = val

    captured = _io.StringIO()
    qa_bypass = os.environ.get("YOKE_QA_GATE_BYPASS", "0") == "1"
    try:
        result = backlog.execute_update(
            item_id=epic_id_int,
            field="status",
            value=derived,
            qa_bypass=qa_bypass,
            rebuild_board=False,
            out=captured,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"WARNING: auto_derive_epic_status: parent-status write raised for epic YOK-{epic_id}: {exc}",
            file=stderr,
        )
        return
    finally:
        for key, prev in previous_env.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    output = captured.getvalue()
    if not result.get("success"):
        snippet = (result.get("error") or "").split("\n")[0][:200] or "unknown"
        print(
            f"WARNING: auto_derive_epic_status: parent-status write failed for epic YOK-{epic_id} "
            f"({parent_status} -> {derived}): {snippet}",
            file=stderr,
        )
        if output:
            print(output.rstrip(), file=stderr)
        return

    if output:
        print(output.rstrip(), file=stdout)

    # Post-write verification
    post_status = query_scalar(
        conn,
        f"SELECT status FROM items WHERE CAST(id AS TEXT)=CAST({p} AS TEXT)",
        (str(epic_id),),
    )
    if post_status != derived:
        print(
            f"WARNING: auto_derive_epic_status: post-write verification failed for "
            f"epic YOK-{epic_id} — expected '{derived}', got '{post_status}'",
            file=stderr,
        )


def _finalize_release_epic_if_ready(
    conn: Any,
    epic_id: str,
    rows: list,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    """Finalize a parent epic from ``release`` to ``done`` via the engine.

    Fires only when every child task is exactly ``done``.  The status write is
    delegated to :func:`done_transition_runner.run` so the engine's
    ``check_done_preconditions``, merge/deploy/recovery gates, GitHub sync,
    board rebuild, and scoped ``YOKE_CLAIM_BYPASS`` remain authoritative --
    auto-derive never writes ``items.status='done'`` itself.  When the engine
    refuses, the parent is left at ``release`` with the engine's failure lines
    surfaced for the operator.
    """
    # Re-entrancy guard: the parent->child cascades that move tasks under a
    # done-transition (``done-cascade:YOK-<id>``) run with ``no_derive=False``
    # in one path (reviewed-implementation -> release), so this hook is reached
    # while the parent is already ``release``.  Never let a downward cascade
    # ping-pong into an upward finalize attempt.
    if os.environ.get("YOKE_CLAIM_BYPASS", "").startswith("done-cascade:"):
        return

    non_done = [(r["task_num"], r["status"]) for r in rows if r["status"] != "done"]
    if non_done:
        detail = ", ".join(f"task {tnum}={st}" for tnum, st in non_done)
        print(
            f"Epic YOK-{epic_id} at release: not auto-finalizing — "
            f"{len(non_done)} child task(s) not done ({detail}).",
            file=stdout,
        )
        return

    try:
        epic_id_int = int(epic_id)
    except (TypeError, ValueError):
        print(
            f"WARNING: auto-finalize: cannot coerce epic id '{epic_id}' to int",
            file=stderr,
        )
        return

    print(
        f"Auto-finalizing epic YOK-{epic_id}: all child tasks done and parent at "
        f"release — routing release -> done through the done-transition engine.",
        file=stdout,
    )

    from yoke_core.engines import done_transition_runner

    # The engine chdirs into the repo root and reseats ``sys.path[0]``; snapshot
    # and restore both so an in-process caller (the task-status mutator and its
    # siblings) is not left with a surprising global cwd / import-path side
    # effect after the finalize returns.
    cwd_before = os.getcwd()
    syspath0_before = sys.path[0] if sys.path else ""
    try:
        rc = done_transition_runner.run(epic_id_int)
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"WARNING: auto-finalize: done-transition engine raised for "
            f"epic YOK-{epic_id}: {exc}",
            file=stderr,
        )
        return
    finally:
        try:
            os.chdir(cwd_before)
        except OSError:  # pragma: no cover - defensive
            pass
        if sys.path:
            sys.path[0] = syspath0_before

    if rc != 0:
        print(
            f"WARNING: auto-finalize: done-transition engine refused epic "
            f"YOK-{epic_id} (exit {rc}); parent left at release. Resolve the "
            f"reported gate and run /yoke usher YOK-{epic_id}.",
            file=stderr,
        )
        return

    print(f"Epic YOK-{epic_id} finalized: release -> done.", file=stdout)
