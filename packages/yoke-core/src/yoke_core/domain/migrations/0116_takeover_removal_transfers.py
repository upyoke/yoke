"""Name the taking run on takeover removals recorded before the field existed.

A takeover records each member it moves as a removal on the run it took
over. Since ``transferred_to_run_id`` was added, that entry names the run the
member moved to, and enrollment reads it as a transfer rather than an
operator's park. Entries written earlier carry only the reason text
"taken over by run X, ...", so every successor read them as parks and left
those items out of the next release. This pass copies X into
``transferred_to_run_id`` on exactly those entries, so runtime code never has
to parse reason text. Every other entry and field is left as it was, and
replay is a no-op.
"""

import re

from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres

_TAKEN_OVER = re.compile(r"^taken over by run ([^\s,;]+)")


def _taker(entry):
    """The run a legacy takeover entry names, or ``None`` when it is not one."""
    if not isinstance(entry, dict) or entry.get("transferred_to_run_id"):
        return None
    match = _TAKEN_OVER.match(str(entry.get("reason") or ""))
    return match.group(1) if match else None


def _rows(conn):
    return conn.execute(
        "SELECT id, membership_removals FROM deployment_runs "
        "WHERE membership_removals IS NOT NULL"
    ).fetchall()


def _decode(raw):
    try:
        entries = json_helper.loads_text(str(raw or "[]"))
    except ValueError:
        return None
    return entries if isinstance(entries, list) else None


def apply(conn):
    """Backfill ``transferred_to_run_id`` from each legacy takeover reason."""
    p = "%s" if connection_is_postgres(conn) else "?"
    for run_id, raw in _rows(conn):
        entries = _decode(raw)
        if not entries:
            continue
        changed = False
        for entry in entries:
            taker = _taker(entry)
            if taker:
                entry["transferred_to_run_id"] = taker
                changed = True
        if changed:
            conn.execute(
                f"UPDATE deployment_runs SET membership_removals={p} WHERE id={p}",
                (json_helper.dumps_compact(entries), run_id),
            )


def invariants(conn):
    """No takeover entry still reads as an operator park."""
    for run_id, raw in _rows(conn):
        for entry in _decode(raw) or ():
            if _taker(entry):
                raise AssertionError(
                    f"deployment run {run_id!r} still has a takeover removal for "
                    f"item {entry.get('item_id')!r} without transferred_to_run_id"
                )
