"""Ensure-register drive cases for wire-carried identity healing."""

from __future__ import annotations

import pytest

from runtime.harness import hook_runner_register as register_module


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
        "yoke_core.domain.events_session_actor.session_actor_lookup",
        lambda _conn, _sid: (True, 3),
    )


def test_existing_placeholder_model_with_wire_model_drives_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **_kw: calls.append(sid) or ("", "c", "p", "m", None),
    )

    drove = register_module.ensure_registered_from_hook(
        _Conn([{"model": "unknown"}]),
        '{"model": "claude-fable-5[1m]"}',
        "s-model",
    )

    assert drove is True
    assert calls == ["s-model"]


def test_wire_placeholder_model_does_not_drive_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("placeholder model must not drive upgrade"),
    )

    assert register_module.ensure_registered_from_hook(
        _Conn([{"model": "unknown"}]),
        '{"model": "<synthetic>"}',
        "s-model-placeholder",
    ) is False


def test_existing_primary_lane_with_wire_lane_drives_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **_kw: calls.append(sid) or ("", "c", "p", "m", None),
    )

    drove = register_module.ensure_registered_from_hook(
        _Conn([{"execution_lane": "primary"}]),
        '{"execution_lane": "DARIUS"}',
        "s-lane",
    )

    assert drove is True
    assert calls == ["s-lane"]


def test_existing_real_lane_with_other_wire_lane_skips(monkeypatch):
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("real lanes must not swap laterally"),
    )

    assert register_module.ensure_registered_from_hook(
        _Conn([{"execution_lane": "DARIUS"}]),
        '{"execution_lane": "ALTMAN"}',
        "s-lane-real",
    ) is False
