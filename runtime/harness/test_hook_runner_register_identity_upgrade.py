"""Ensure-register drive cases for wire-carried model-fact healing."""

from __future__ import annotations

from yoke_core.hooks import registration as register_module

from runtime.harness.register_identity_upgrade_test_support import (
    _Conn,
    _patch_existing_row,
)


def test_existing_coarse_model_with_better_wire_model_drives_reregister(monkeypatch):
    # A row that still holds the bare family id (recorded before the store
    # answered) must take the later store measurement.
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **_kw: calls.append(sid) or ("", "c", "p", "m", None),
    )

    drove = register_module.ensure_registered_from_hook(
        _Conn([{"model": "grok-4.6", "executor_surface": "cursor-cli", "executor": "cursor"}]),
        '{"model": "cursor-grok-4.6-xhigh"}',
        "s-model-measured",
    )

    assert drove is True
    assert calls == ["s-model-measured"]


def test_a_differing_attestation_drives_reregister_on_every_harness(monkeypatch):
    # The served column takes the newest attestation, so a session that
    # switched model or effort mid-run heals to the later value. Only the
    # requested columns are write-once.
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda _p, sid, **_kw: calls.append(sid),
    )

    assert (
        register_module.ensure_registered_from_hook(
            _Conn([{"model": "claude-opus-4-7[1m]", "executor_surface": "claude-cli",
                 "executor": "claude-code"}]),
            '{"model": "claude-sonnet-4-6"}',
            "s-model-switched",
        )
        is True
    )
    assert calls == ["s-model-switched"]


def test_a_stored_request_is_not_rewritten_by_a_later_one(monkeypatch):
    # The ask was fixed at launch; a later reading fills a gap only.
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("a stored request must not be rewritten"),
    )

    assert (
        register_module.ensure_registered_from_hook(
            _Conn([{"requested_model": "claude-opus-5[1m]",
                    "executor_surface": "claude-cli", "executor": "claude-code"}]),
            '{"requested_model": "haiku"}',
            "s-ask-stable",
        )
        is False
    )


def test_agreeing_wire_model_does_not_drive_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("a settled model must not re-register"),
    )

    assert (
        register_module.ensure_registered_from_hook(
            _Conn(
                [{"model": "cursor-grok-4.6-xhigh", "executor_surface": "cursor-cli",
                        "executor": "cursor"}]
            ),
            '{"model": "cursor-grok-4.6-xhigh"}',
            "s-model-settled",
        )
        is False
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

    assert (
        register_module.ensure_registered_from_hook(
            _Conn([{"model": "unknown"}]),
            '{"model": "<synthetic>"}',
            "s-model-placeholder",
        )
        is False
    )
