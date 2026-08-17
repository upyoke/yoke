"""Ensure-register drive cases for wire-carried identity healing."""

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
    """Stand in for a live, actor-bound row so the fake conn's single row
    is consumed by the identity-upgrade probe under test."""
    monkeypatch.setattr(
        "yoke_core.domain.sessions_ended_recovery.session_registration_state",
        lambda _conn, _sid: (True, 3, False),
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


def test_unresolved_lane_drives_reregister_from_project_routing(monkeypatch):
    """A row the sentinel left unroutable repairs itself on any hook event.

    Nothing rides the wire here — the executor on the row plus the project's
    routing policy are the whole input, which is what lets a session stamped
    before its policy could be read heal without operator action.
    """
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **_kw: calls.append(sid) or ("", "c", "p", "m", None),
    )
    monkeypatch.setattr(
        "yoke_core.hooks.registration_identity.project_lane_for_executor",
        lambda _conn, _project, _executor, **_kw: "DARIUS",
    )

    drove = register_module.ensure_registered_from_hook(
        _Conn([{"execution_lane": "primary", "executor": "claude-code"}]),
        "{}",
        "s-lane-heal",
        project_id=1,
    )

    assert drove is True
    assert calls == ["s-lane-heal"]


def test_healed_lane_stops_driving_reregister(monkeypatch):
    """Once the row carries a real lane the probe goes quiet again."""
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("a resolved lane must not re-register"),
    )
    monkeypatch.setattr(
        "yoke_core.hooks.registration_identity.project_lane_for_executor",
        lambda *_a, **_kw: pytest.fail("resolved rows must not consult routing"),
    )

    assert register_module.ensure_registered_from_hook(
        _Conn([{"execution_lane": "DARIUS", "executor": "claude-code"}]),
        "{}",
        "s-lane-healed",
        project_id=1,
    ) is False


def test_unresolvable_lane_does_not_drive_reregister(monkeypatch):
    """A project with no mapping for this executor must not loop forever."""
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("an unresolvable lane must not re-register"),
    )
    monkeypatch.setattr(
        "yoke_core.hooks.registration_identity.project_lane_for_executor",
        lambda _conn, _project, _executor, **_kw: "primary",
    )

    assert register_module.ensure_registered_from_hook(
        _Conn([{"execution_lane": "primary", "executor": "some-other-harness"}]),
        "{}",
        "s-lane-unmapped",
        project_id=1,
    ) is False


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
