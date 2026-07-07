"""Row-count collapse detection + DataLossDetected emission.

Sibling of ``db_error_hook``. Owns the DDL pattern, critical-table list,
collapse dataclasses, the ``check_row_count_collapse`` analyzer, and the
``DataLossDetected`` event emitter triggered when collapse is found.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from yoke_core.domain import project_scratch_dir
from yoke_core.domain.db_helpers import connect


DDL_PATTERNS = re.compile(
    r"(?i)\b(ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+TABLE|"
    r"PRAGMA\s+foreign_keys|DELETE\s+FROM\s+\w+\s*;?\s*$|"
    r"TRUNCATE|\.restore|\.import)",
    re.MULTILINE,
)

CRITICAL_TABLES = ["items", "epic_tasks", "events", "epic_progress_notes", "qa_runs"]


@dataclass
class CollapseEntry:
    """A single table's row-count collapse."""

    table: str
    baseline: int
    current: int
    drop_pct: float


@dataclass
class CollapseResult:
    """Result of row-count collapse analysis."""

    collapsed: list[CollapseEntry] = field(default_factory=list)
    message: str = ""


def check_row_count_collapse(
    db_path: str,
    command: str,
    session_id: str = "",
    script_dir: str = "",
) -> CollapseResult:
    """Check for catastrophic row-count collapse after DDL operations.

    Only triggers when *command* contains DDL-like SQL patterns.
    Maintains a session-scoped baseline and compares current counts.
    """
    if not db_path:
        return CollapseResult()

    if not DDL_PATTERNS.search(command):
        return CollapseResult()

    if not session_id:
        session_id = os.environ.get(
            "YOKE_SESSION_ID",
            os.environ.get("CLAUDE_SESSION_ID", "default"),
        )

    baseline_file = str(
        project_scratch_dir.storage_path(
            "db_error_hook", "collapse-state", f"baseline-{session_id}.json"
        )
    )

    try:
        baseline: dict[str, int] = {}
        if os.path.isfile(baseline_file):
            with open(baseline_file) as f:
                baseline = json.load(f)

        conn = connect(db_path)
        current: dict[str, int] = {}
        for table in CRITICAL_TABLES:
            try:
                row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
                current[table] = row[0] if row else 0
            except Exception:
                pass
        conn.close()

        if not baseline:
            with open(baseline_file, "w") as f:
                json.dump(current, f)
            return CollapseResult()

        collapsed: list[CollapseEntry] = []
        for table in CRITICAL_TABLES:
            if table not in baseline or table not in current:
                continue
            base_count = baseline[table]
            curr_count = current[table]
            if base_count <= 0:
                continue
            drop_pct = ((base_count - curr_count) / base_count) * 100
            if drop_pct > 50 or (base_count > 10 and curr_count <= 1):
                collapsed.append(
                    CollapseEntry(
                        table=table,
                        baseline=base_count,
                        current=curr_count,
                        drop_pct=round(drop_pct, 1),
                    )
                )

        if not collapsed:
            return CollapseResult()

        lines = [
            "CRITICAL DATA LOSS DETECTED: The preceding Bash command "
            "may have caused catastrophic row-count collapse in yoke.db."
        ]
        for c in collapsed:
            lines.append(
                f"  - Table '{c.table}': {c.baseline} -> {c.current} rows ({c.drop_pct}% drop)"
            )
        lines.append(
            "RECOVERY: Check the affected migration_audit row's "
            "`backup_path` for the Postgres rollback dump created by "
            "`migration_apply`. Do NOT continue making DB mutations until "
            "the data loss is investigated. The command that triggered this alarm: "
            + command[:300]
        )

        if script_dir:
            _emit_data_loss_event(script_dir, collapsed, command, db_path)

        return CollapseResult(
            collapsed=collapsed,
            message="\n".join(lines),
        )

    except Exception:
        return CollapseResult()


def _emit_data_loss_event(
    script_dir: str,
    collapsed: list[CollapseEntry],
    command: str,
    db_path: str,
) -> None:
    """Emit DataLossDetected via the native Python emitter."""
    del script_dir  # unused — kept for API compat; native emitter resolves DB internally
    context_obj = {
        "collapsed_tables": [
            {
                "table": c.table,
                "baseline": c.baseline,
                "current": c.current,
                "drop_pct": c.drop_pct,
            }
            for c in collapsed
        ],
        "command": command[:500],
        "db_path": db_path,
    }
    try:
        from yoke_core.domain.events import emit_event as _native_emit
        _native_emit(
            "DataLossDetected",
            event_kind="system",
            event_type="db_alarm",
            source_type="hook",
            severity="FATAL",
            outcome="alarm",
            context=context_obj,
        )
    except Exception:
        pass
