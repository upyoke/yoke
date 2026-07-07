"""Events CRUD, registry, and reporting logic for the Yoke event platform.

This module exports the full public surface; implementation is split into
events_writes.py (schema/init/insert/prune/severity), events_queries.py
(list/count/tail/query), and events_reporting.py (registry/discovery).

CLI usage::

    python3 -m yoke_core.domain.events_crud <subcmd> [args...]

Subcommands:

    init, insert, list, query, count, anomalies, prune, tail,
    severity-config, severity-check, registry (add/get/list/update/
    deprecate/delete/count/discover/audit/diff)

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

if __name__ == "__main__":
    sys.modules.setdefault("yoke_core.domain.events_crud", sys.modules[__name__])


VALID_SOURCE_TYPES = ("agent", "backend", "frontend", "system", "script", "hook", "skill")

# Severity + SELECT/format primitives live in the import-order leaf
# ``events_select`` (re-exported here for existing consumers); the read
# modules import the leaf directly so importing them first no longer
# re-enters this module's tail imports.
from yoke_core.domain.events_select import (  # noqa: E402,F401
    _EVT_SELECT_COLS,
    _REG_SELECT_COLS,
    EVT_COLUMN_NAMES,
    SEVERITY_ORDER,
    VALID_SEVERITIES,
    _format_rows,
    severity_num,
)

# Retention tiers: severity -> days (None = forever). DEBUG is the
# on-demand-capture tier (dropped at the default INFO write floor; turned on
# by lowering severity_config to DEBUG), so its retention is the shortest —
# any debug-session exhaust auto-cleans within a day. Keep in lockstep with
# the offset_days literals in events_prune.cmd_prune.
_RETENTION_DAYS: Dict[str, Optional[int]] = {
    "DEBUG": 1,
    "INFO": 30,
    "WARN": 90,
    "STATUS": None,
    "ERROR": None,
    "FATAL": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_event_item_id(item_id: Optional[str]) -> Optional[str]:
    """Coerce event item IDs to canonical bare-numeric form, or None.

    The indexed ``events.item_id`` column stores bare integers
    exclusively. Composite work-unit strings like
    ``epic-1318-task-3`` or lane sentinels like ``STRATEGIZE`` / ``DOCTOR``
    / ``run-20260417-002`` return ``None`` here; callers should decompose
    them via :func:`decompose_work_unit` and stash the sentinel in
    ``context.work_unit`` before reaching this function.
    """
    if item_id is None:
        return None
    text = str(item_id).strip()
    if not text:
        return None
    bare = re.sub(r"^[Yy][Oo][Kk]-", "", text)
    if bare.isdigit():
        return bare.lstrip("0") or "0"
    return None


_EPIC_TASK_RE = re.compile(r"^epic-(\d+)-task-(\d+)$", re.IGNORECASE)


def decompose_work_unit(
    item_id: Optional[str],
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """Split a work-unit identifier into ``(item_id, task_num, sentinel)``.

    - ``None`` / empty -> ``(None, None, None)``
    - Bare integer or ``YOK-N`` -> ``(bare, None, None)``
    - ``epic-N-task-M`` -> ``(N, M, None)``
    - Anything else (lane sentinels like ``STRATEGIZE`` / ``DOCTOR``,
      deployment run IDs like ``run-20260417-002``) -> ``(None, None, raw)``

    The sentinel is preserved verbatim so the emitter can surface it in
    ``context.work_unit`` without polluting the indexed integer column.
    """
    if item_id is None:
        return None, None, None
    text = str(item_id).strip()
    if not text:
        return None, None, None
    bare = re.sub(r"^[Yy][Oo][Kk]-", "", text)
    if bare.isdigit():
        return bare.lstrip("0") or "0", None, None
    epic_match = _EPIC_TASK_RE.match(text)
    if epic_match:
        epic_id = epic_match.group(1).lstrip("0") or "0"
        task_num = int(epic_match.group(2))
        return epic_id, task_num, None
    return None, None, text


class EventSeverityCasingError(ValueError):
    """Raised when an event severity string is outside the canonical enum."""


def normalize_severity(sev: str) -> str:
    """Return the canonical ``VALID_SEVERITIES`` form for ``sev``.

    Accepts any case-folded equivalent of the canonical names
    (``"warning"``/``"WARNING"``/``"Warn"``/``"warn"`` all map to ``"WARN"``;
    lowercase ``"info"``/``"Info"`` to ``"INFO"``; etc.). Raises
    :class:`EventSeverityCasingError` for any value whose case-folded form is
    not in the canonical name set.

    Writer-time normalization paired with reject-unknown is the write-side
    backstop for `severity_num`'s read-side default-to-INFO behavior.
    """
    if not isinstance(sev, str) or not sev.strip():
        raise EventSeverityCasingError(
            f"severity must be a non-empty string, got {sev!r}"
        )
    folded = sev.strip().upper()
    if folded == "WARNING":
        return "WARN"
    if folded in VALID_SEVERITIES:
        return folded
    raise EventSeverityCasingError(
        f"severity must be one of {', '.join(VALID_SEVERITIES)} "
        f"(case-insensitive, with WARNING aliased to WARN); got {sev!r}"
    )


# ---------------------------------------------------------------------------
# Re-exports from child modules
# ---------------------------------------------------------------------------

from yoke_core.domain.events_writes import (  # noqa: E402
    _create_events_table,
    check_severity,
    cmd_init,
    cmd_insert,
    cmd_prune,
    cmd_severity_check,
    cmd_severity_config_list,
    cmd_severity_config_set,
)

from yoke_core.domain.events_queries import (  # noqa: E402
    _build_where,
    cmd_anomalies,
    cmd_count,
    cmd_list,
    cmd_query,
    cmd_tail,
)

from yoke_core.domain.events_reporting import (  # noqa: E402
    _discover_python_event_names,
    _extract_event_name_from_line,
    _join_continuation_lines,
    _py_call_name,
    _py_string_value,
    _validate_event_name,
    cmd_registry_add,
    cmd_registry_audit,
    cmd_registry_count,
    cmd_registry_delete,
    cmd_registry_deprecate,
    cmd_registry_diff,
    cmd_registry_discover,
    cmd_registry_get,
    cmd_registry_list,
    cmd_registry_update,
)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point — delegates to ``events_crud_cli.main``.

    A late import keeps ``events_crud`` import-time free of any reference
    to ``events_crud_cli`` so the module path
    ``python3 -m yoke_core.domain.events_crud`` keeps working without
    introducing a load-time cycle.
    """
    from yoke_core.domain.events_crud_cli import main as _cli_main
    return _cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
