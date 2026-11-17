"""Ensure-register drive cases for level, surface, and version healing.

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
        lambda payload, sid, **_kw: calls.append(sid) or ("registered", "c", "p", "m", None),
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

    assert drove == "registered"
    assert calls == ["s-version"]


def test_existing_null_surface_with_wire_surface_drives_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **_kw: calls.append(sid) or ("registered", "c", "p", "m", None),
    )

    drove = register_module.ensure_registered_from_hook(
        _Conn([{"executor_surface": None}]),
        '{"entrypoint": "codex-cli"}',
        "s-surface",
    )

    assert drove == "registered"
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
            _Conn([{"execution_level": "SENIOR", "executor": "codex"}]),
            '{"executor_version": "0.150.0"}',
            "s-version-only",
        )
        == "exists"
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
                    {"execution_level": "SENIOR", "executor": executor},
                ]
            ),
            f'{{"entrypoint": "{wire_surface}"}}',
            "s-resolved-surface",
        )
        == "exists"
    )


def test_a_wire_level_without_model_facts_cannot_drive_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **_kw: calls.append(sid) or ("registered", "c", "p", "m", None),
    )

    drove = register_module.ensure_registered_from_hook(
        _Conn([{"execution_level": "primary"}]),
        '{"execution_level": "SENIOR"}',
        "s-level",
    )

    assert drove == "exists"
    assert calls == []


def _unresolved_row(executor: str, **facts) -> dict:
    """A stored row the sentinel left unroutable, with its model facts."""
    row = {
        "execution_level": "primary",
        "executor": executor,
        "model": None,
        "requested_model": None,
        "reasoning_effort": None,
        "requested_reasoning_effort": None,
    }
    row.update(facts)
    return row


# Nothing is stored in either level store: the project override read and the
# universe read each find no row, so the shipped options decide.
_NO_STORED_LEVELS = (None, None)


@pytest.mark.parametrize(
    "facts",
    [
        {"model": "claude-opus-5-5", "reasoning_effort": "medium"},
        {
            "requested_model": "claude-opus-5-5[1m]",
            "requested_reasoning_effort": "medium",
        },
    ],
)
def test_unresolved_level_drives_reregister_from_matching_option(monkeypatch, facts):
    """A row the sentinel left unroutable repairs itself on any hook event.

    Nothing rides the wire here: the row's executor and model facts matched
    against the levels the project reads are the whole input, which is what
    lets a session stamped before a matching option existed heal without
    operator action.
    """
    _patch_existing_row(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **_kw: calls.append(sid) or ("registered", "c", "p", "m", None),
    )

    drove = register_module.ensure_registered_from_hook(
        _Conn([_unresolved_row("claude-code", **facts), *_NO_STORED_LEVELS]),
        "{}",
        "s-level-heal",
        project_id=1,
    )

    assert drove == "registered"
    assert calls == ["s-level-heal"]


def test_healed_level_stops_driving_reregister(monkeypatch):
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("matching actual facts must not re-register"),
    )
    row = _unresolved_row(
        "claude-code", model="claude-opus-5-5", reasoning_effort="medium"
    )
    row["execution_level"] = "SENIOR"
    assert (
        register_module.ensure_registered_from_hook(
            _Conn([row, *_NO_STORED_LEVELS]), "{}", "s-level-healed", project_id=1
        )
        == "exists"
    )


@pytest.mark.parametrize(
    "executor,facts",
    [
        ("claude-code", {"model": "claude-unlisted"}),
        ("claude-code", {}),
        ("some-other-harness", {"model": "claude-opus-5-5"}),
    ],
)
def test_unresolvable_level_does_not_drive_reregister(monkeypatch, executor, facts):
    """A session no option matches must not re-register on every event."""
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("an unresolvable level must not re-register"),
    )

    assert (
        register_module.ensure_registered_from_hook(
            _Conn([_unresolved_row(executor, **facts), *_NO_STORED_LEVELS]),
            "{}",
            "s-level-unmapped",
            project_id=1,
        )
        == "exists"
    )


def test_existing_real_level_with_other_wire_level_skips(monkeypatch):
    _patch_existing_row(monkeypatch)
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda *_a, **_kw: pytest.fail("real levels must not swap laterally"),
    )

    assert (
        register_module.ensure_registered_from_hook(
            _Conn([{"execution_level": "SENIOR"}]),
            '{"execution_level": "INTERN"}',
            "s-level-real",
        )
        == "exists"
    )


def test_actual_changed_model_refreshes_a_real_level(monkeypatch):
    _patch_existing_row(monkeypatch)
    calls = []
    monkeypatch.setattr(
        register_module,
        "_register_from_hook",
        lambda payload, sid, **kw: calls.append(sid) or ("registered", "c", "p", "m", None),
    )
    row = _unresolved_row(
        "claude-code", model="claude-haiku-5-5", reasoning_effort="high"
    )
    row["execution_level"] = "SENIOR"
    assert (
        register_module.ensure_registered_from_hook(
            _Conn([row, *_NO_STORED_LEVELS]), "{}", "s-changed", project_id=1
        )
        == "registered"
    )
    assert calls == ["s-changed"]
