"""Ensure-register does not let a Cursor family id overwrite a measurement."""

from __future__ import annotations

import pytest

from yoke_core.hooks import registration as register_module


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
    monkeypatch.setattr(
        "yoke_core.domain.sessions_ended_recovery.session_registration_state",
        lambda _conn, _sid: (True, 3, False),
    )


def test_bare_family_id_does_not_drive_reregister_over_a_measurement(monkeypatch):
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail(
            "a measurement must not be replaced by a family id"
        ),
    )

    assert (
        register_module.ensure_registered_from_hook(
            _Conn(
                [
                    {
                        "model": "cursor-grok-4.6-xhigh",
                        "executor_surface": "cursor-cli",
                        "executor": "cursor",
                    }
                ]
            ),
            '{"model": "grok-4.6"}',
            "s-model-measured",
        )
        is False
    )
