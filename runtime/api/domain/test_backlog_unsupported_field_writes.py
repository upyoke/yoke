"""Tests for the unsupported-field write bridge.

Focus: the ``architecture_impact`` branch validates + normalizes to the
canonical enum form before persisting, so this operator/repair surface
can never store a stray-whitespace value (e.g. ``"architecture_model_change\\n"``)
that a downstream comparison forgets to strip. The low-level DB writer is
monkeypatched so these stay pure-logic tests with no test-DB dependency.
"""

from __future__ import annotations

import io

from yoke_core.domain import backlog_unsupported_field_writes as bridge


def test_architecture_impact_is_normalized_before_write(monkeypatch):
    captured = {}

    def _fake_update(conn, item_id, field, value):
        captured["field"] = field
        captured["value"] = value

    monkeypatch.setattr(bridge, "_update_item_field", _fake_update)

    result = bridge._apply_shell_fallback(
        None, 42, "architecture_impact",
        "architecture_model_change\n", io.StringIO(),
    )

    assert result == {"success": True}
    assert captured["field"] == "architecture_impact"
    # Trailing newline / case stripped to the canonical enum value.
    assert captured["value"] == "architecture_model_change"


def test_architecture_impact_case_and_space_normalized(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        bridge, "_update_item_field",
        lambda conn, item_id, field, value: captured.__setitem__("value", value),
    )

    result = bridge._apply_shell_fallback(
        None, 7, "architecture_impact", "  Path_Context_Only  ", io.StringIO(),
    )

    assert result == {"success": True}
    assert captured["value"] == "path_context_only"


def test_invalid_architecture_impact_rejected_without_write(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        bridge, "_update_item_field",
        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1),
    )

    result = bridge._apply_shell_fallback(
        None, 7, "architecture_impact", "major_refactor", io.StringIO(),
    )

    assert result["success"] is False
    assert "not a known value" in result["error"]
    assert calls["n"] == 0  # nothing persisted for an invalid value


def test_unknown_field_still_rejected(monkeypatch):
    monkeypatch.setattr(bridge, "_update_item_field", lambda *a, **k: None)

    result = bridge._apply_shell_fallback(
        None, 7, "totally_unknown_field", "x", io.StringIO(),
    )

    assert result["success"] is False
    assert "not supported" in result["error"]
