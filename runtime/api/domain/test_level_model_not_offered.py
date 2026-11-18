"""A level option whose model the installed CLI does not list names why."""

from __future__ import annotations

import io
import json

import pytest

from yoke_cli.commands.adapters.universe_levels import write_capacity
from yoke_contracts.session_control.native_models import models_reading, native_model
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import universe_level_capacity_read as reader
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_placement import place_level

from runtime.api.domain.session_launch_level_test_support import (
    CODEX_SOL,
    LEVEL,
    add_surface,
    level_connection,
    pin_live_workers,
    weekly,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization

MACHINE = "workshop-mac"
SURFACE = "codex-cli"
OLD_CLI = "0.161.0"
NOT_OFFERED = (
    "native_model_not_offered: codex-cli 0.161.0 on workshop-mac does not list "
    "gpt-6.2-sol; run `codex update` there, then "
    "`yoke relay probe-models --surface codex-cli`"
)


@pytest.fixture
def old_codex(monkeypatch):
    """One Codex machine whose CLI build lists gpt-6.1-sol but not gpt-6.2-sol."""
    pin_live_workers(monkeypatch, {})
    conn = level_connection(CODEX_SOL)
    conn.execute("ALTER TABLE projects ADD COLUMN name TEXT")
    conn.execute("ALTER TABLE projects ADD COLUMN retired_at TEXT")
    monkeypatch.setattr(reader, "_now", lambda: parse_instant(NOW))
    monkeypatch.setattr(reader, "live_session_counts", lambda *a, **kw: ())
    add_surface(conn, MACHINE, SURFACE, [weekly(80.0)])
    listing = models_reading(
        SURFACE,
        [native_model("gpt-6.1-sol", reasoning_efforts=["low", "medium", "high"])],
        source="codex fixture",
        observed_at=NOW,
    )
    conn.execute(
        "UPDATE session_relays SET hostname = ?, surface_native_models = ?, "
        "surface_versions = ?",
        (MACHINE, json.dumps({SURFACE: listing}), json.dumps({SURFACE: OLD_CLI})),
    )
    conn.commit()
    return conn


def test_placement_explanation_names_the_missing_model_and_cli_version(old_codex):
    placement = place_level(
        old_codex,
        auth=authorization(actor_id=1),
        project_id=10,
        level=LEVEL,
        machine_id=None,
        now=parse_instant(NOW),
        eligibility=derive_launch_eligibility,
    )

    assert placement.chosen is None
    assert [
        (c.machine_id, c.blocked) for c in placement.candidates if c.surface == SURFACE
    ] == [(MACHINE, NOT_OFFERED)]
    assert NOT_OFFERED in placement.reason


def test_yoke_models_names_the_missing_model_and_cli_version(old_codex):
    result = reader.read_level_capacity(
        old_codex, authorize=lambda _: authorization()
    )
    out = io.StringIO()

    write_capacity(result, out)

    assert f"[blocked: {SURFACE}: {NOT_OFFERED};" in out.getvalue()


def test_upgraded_cli_listing_clears_the_reason(old_codex):
    listing = models_reading(
        SURFACE,
        [native_model("gpt-6.2-sol", reasoning_efforts=["low", "medium", "high"])],
        source="codex fixture",
        observed_at=NOW,
    )
    old_codex.execute(
        "UPDATE session_relays SET surface_native_models = ?, surface_versions = ?",
        (json.dumps({SURFACE: listing}), json.dumps({SURFACE: "0.170.0"})),
    )
    old_codex.commit()

    result = reader.read_level_capacity(
        old_codex, authorize=lambda _: authorization()
    )

    assert result["levels"][0]["options"][0]["now"]["state"] == "can_launch"
    assert "native_model_not_offered" not in str(result)
