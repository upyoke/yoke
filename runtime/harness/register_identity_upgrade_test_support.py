"""Fakes shared by the ensure-register identity-healing suites.

The probes under test each read one row, so the fake connection hands out
its rows in order and a test supplies exactly the rows its probe chain
consumes.
"""

from __future__ import annotations


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, rows):
        self._rows = list(rows)

    def execute(self, *_args, **_kwargs):
        return _Cursor(self._rows.pop(0))


def _patch_existing_row(monkeypatch):
    """Stand in for a live, actor-bound row so the fake conn's single row
    is consumed by the identity-upgrade probe under test."""
    monkeypatch.setattr(
        "yoke_core.domain.sessions_ended_recovery.session_registration_state",
        lambda _conn, _sid: (True, 3, False),
    )


__all__ = ["_Conn", "_Cursor", "_patch_existing_row"]
