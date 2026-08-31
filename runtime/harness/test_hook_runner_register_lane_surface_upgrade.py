"""Ensure-register drive cases for lane, surface, and version healing.

Split from the model-fact suite so each file stays inside the authored-file
budget; the probes share one fake connection helper.
"""

from __future__ import annotations

import pytest

from yoke_core.hooks import registration as register_module

from runtime.harness.register_identity_upgrade_test_support import (
    _Conn,
    _patch_existing_row,
)


def test_existing_missing_version_with_wire_version_drives_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **_kw: calls.append(sid) or ("", "c", "p", "m", None),
    )

    drove = register_module.ensure_registered_from_hook(
        _Conn(
            [
                {
                    "executor_surface": "codex-cli",
                    "executor_version": None,
                }
            ]
        ),
        '{"entrypoint": "codex-cli", "executor_version": "0.150.0"}',
        "s-version",
    )

    assert drove is True
    assert calls == ["s-version"]


def test_existing_null_surface_with_wire_surface_drives_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **_kw: calls.append(sid) or ("", "c", "p", "m", None),
    )

    drove = register_module.ensure_registered_from_hook(
        _Conn([{"executor_surface": None}]),
        '{"entrypoint": "codex-cli"}',
        "s-surface",
    )

    assert drove is True
    assert calls == ["s-surface"]


def test_wire_version_without_surface_does_not_drive_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("an unpaired version must not register"),
    )

    assert (
        register_module.ensure_registered_from_hook(
            _Conn([{"execution_lane": "DARIUS", "executor": "codex"}]),
            '{"executor_version": "0.150.0"}',
            "s-version-only",
        )
        is False
    )


@pytest.mark.parametrize(
    ("executor", "stored_surface", "wire_surface"),
    [
        ("codex", "codex-cli", "codex-desktop"),
        ("claude-code", "claude-cli", "claude-desktop"),
        ("cursor", "cursor-desktop", "cursor-cli"),
    ],
)
def test_existing_resolved_surface_is_never_replaced(
    monkeypatch,
    executor: str,
    stored_surface: str,
    wire_surface: str,
) -> None:
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("resolved surfaces are write-once"),
    )

    assert (
        register_module.ensure_registered_from_hook(
            _Conn(
                [
                    {"executor_surface": stored_surface},
                    {"execution_lane": "DARIUS", "executor": executor},
                ]
            ),
            f'{{"entrypoint": "{wire_surface}"}}',
            "s-resolved-surface",
        )
        is False
    )


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

    assert (
        register_module.ensure_registered_from_hook(
            _Conn([{"execution_lane": "DARIUS", "executor": "claude-code"}]),
            "{}",
            "s-lane-healed",
            project_id=1,
        )
        is False
    )


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

    assert (
        register_module.ensure_registered_from_hook(
            _Conn([{"execution_lane": "primary", "executor": "some-other-harness"}]),
            "{}",
            "s-lane-unmapped",
            project_id=1,
        )
        is False
    )


def test_existing_real_lane_with_other_wire_lane_skips(monkeypatch):
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("real lanes must not swap laterally"),
    )

    assert (
        register_module.ensure_registered_from_hook(
            _Conn([{"execution_lane": "DARIUS"}]),
            '{"execution_lane": "ALTMAN"}',
            "s-lane-real",
        )
        is False
    )
