"""Tests for the config-tunable stale-heartbeat TTL in sessions_analytics_core.

The stale-heartbeat TTL change moved the literal `20` and `{"codex": 60}`
constants in `sessions_analytics_core` behind machine settings so prose
and code share one tunable. These tests assert the indirection is real —
overriding the config keys changes the resolved values returned by `get_int`, and by
extension the constants that read through it at module load.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from yoke_core.domain import runtime_settings


def _write_config(path: Path, **pairs: str | int) -> None:
    lines = [f"{key}={value}" for key, value in pairs.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestStaleTtlConfigIndirection:
    """Overriding explicit fixture keys must change the resolved TTL."""

    def test_default_key_falls_through_when_unset(self, tmp_path: Path):
        config_path = tmp_path / "config"
        config_path.write_text("# empty\n", encoding="utf-8")
        assert (
            runtime_settings.get_int(
                "session_stale_ttl_minutes", 20, config_path=config_path,
            )
            == 20
        )

    def test_default_key_override_changes_value(self, tmp_path: Path):
        config_path = tmp_path / "config"
        _write_config(config_path, session_stale_ttl_minutes=45)
        assert (
            runtime_settings.get_int(
                "session_stale_ttl_minutes", 20, config_path=config_path,
            )
            == 45
        )

    def test_codex_override_key_falls_through_when_unset(self, tmp_path: Path):
        config_path = tmp_path / "config"
        config_path.write_text("# empty\n", encoding="utf-8")
        assert (
            runtime_settings.get_int(
                "session_stale_ttl_minutes_codex_override",
                60,
                config_path=config_path,
            )
            == 60
        )

    def test_codex_override_key_changes_value(self, tmp_path: Path):
        config_path = tmp_path / "config"
        _write_config(
            config_path,
            session_stale_ttl_minutes_codex_override=120,
        )
        assert (
            runtime_settings.get_int(
                "session_stale_ttl_minutes_codex_override",
                60,
                config_path=config_path,
            )
            == 120
        )

    def test_module_constants_resolve_through_get_int(self, monkeypatch):
        """The module constants must be sourced from runtime_settings.get_int.

        Patch the resolver, reload the module, and assert the constants
        carry the patched values. This proves the indirection is live —
        a literal-only refactor would not move when the resolver changes.
        """
        captured: dict[str, int] = {}

        def fake_get_int(
            key: str, default: int, *, config_path=None,  # noqa: ARG001
        ) -> int:
            value = {
                "session_stale_ttl_minutes": 17,
                "session_stale_ttl_minutes_codex_override": 71,
            }.get(key, default)
            captured[key] = value
            return value

        monkeypatch.setattr(
            "yoke_core.domain.runtime_settings.get_int", fake_get_int,
        )

        # Force a re-import so module-load-time reads pick up the patched
        # resolver. importlib.reload() is the canonical surface.
        from yoke_core.domain import sessions_analytics_core

        importlib.reload(sessions_analytics_core)

        assert sessions_analytics_core.DEFAULT_STALE_THRESHOLD_MINUTES == 17
        assert (
            sessions_analytics_core.EXECUTOR_STALE_TTL_OVERRIDES_MINUTES["codex"]
            == 71
        )
        assert captured == {
            "session_stale_ttl_minutes": 17,
            "session_stale_ttl_minutes_codex_override": 71,
        }

        # Reload again with the real resolver so subsequent tests see the
        # production values, not the patched ones.
        monkeypatch.undo()
        importlib.reload(sessions_analytics_core)
