"""Fakes shared by the ensure-register identity-healing suites.

The probes under test each read one row, so the fake connection hands out
its rows in order and a test supplies exactly the rows its probe chain
consumes.
"""

from __future__ import annotations
import json
from yoke_contracts.model_reference_data import MODEL_RECORDS


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, rows):
        self._rows = list(rows)

    def execute(self, sql, *_args, **_kwargs):
        if "model_reference_revisions" in sql:
            return _Cursor(
                (
                    "fixture",
                    "1970-01-01T00:00:00Z",
                    "1970-01-01T00:00:00Z",
                    None,
                    json.dumps([record.to_dict() for record in MODEL_RECORDS]),
                    "fixture",
                    None,
                    "shipped",
                )
            )
        return _Cursor(self._rows.pop(0))


def _patch_existing_row(monkeypatch):
    """Stand in for a live, actor-bound row so the fake conn's single row
    is consumed by the identity-upgrade probe under test."""
    monkeypatch.setattr(
        "yoke_core.domain.sessions_ended_recovery.session_registration_state",
        lambda _conn, _sid: (True, 3, False),
    )


__all__ = ["_Conn", "_Cursor", "_patch_existing_row"]
