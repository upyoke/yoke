"""The preflight rehearses exactly the fleet a project's model declares."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import migration_model_fleet as fleets
from yoke_core.domain import project_checkout_locations
from runtime.api.tools import migration_fleet_selection as selection
from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed


def _declare(monkeypatch: pytest.MonkeyPatch, fleet: dict | None) -> None:
    capability = governed_postgres_test_seed()
    model = capability["models"]["primary"]
    model["runner"]["config"]["modules_dir"] = "service/migrations"
    if fleet is not None:
        model["fleet"] = fleet
    monkeypatch.setattr(fleets, "read_capability", lambda _project: (capability, ""))


def test_undeclared_fleet_is_refused_with_the_declaration_recipe(monkeypatch) -> None:
    _declare(monkeypatch, None)
    target, why = selection.resolve("platform")
    assert target is None
    assert "declares no fleet" in why


def test_fleet_none_has_nothing_to_rehearse(monkeypatch) -> None:
    _declare(monkeypatch, {"kind": "none", "reason": "host-local SQLite"})
    target, why = selection.resolve("buzz")
    assert target is None
    assert "host-local SQLite" in why
    assert "requires no receipt" in why


def test_unknown_model_names_the_declared_ones(monkeypatch) -> None:
    _declare(monkeypatch, {"kind": "engine_tenants"})
    target, why = selection.resolve("yoke", "secondary")
    assert target is None
    assert "['primary']" in why


def _named() -> dict:
    return {
        "kind": "named_databases",
        "names": ["service_registry"],
        "converge_argv": ["python", "-m", "service.schema", "init"],
        "schema_shape_sources": ["service/schema.py"],
    }


def test_named_fleet_without_a_checkout_names_the_registration(monkeypatch) -> None:
    _declare(monkeypatch, _named())
    monkeypatch.setattr(
        project_checkout_locations, "checkout_for_project_slug", lambda _p: None
    )
    target, why = selection.resolve("platform")
    assert target is None
    assert "yoke project register" in why


def test_named_fleet_rehearses_its_declared_databases_from_the_checkout(
    monkeypatch, tmp_path: Path
) -> None:
    history = tmp_path / "service" / "migrations"
    history.mkdir(parents=True)
    (history / "0001_baseline.py").write_text("def apply(conn):\n    pass\n")
    (tmp_path / "service" / "schema.py").write_text("TABLES = {}\n")
    _declare(monkeypatch, _named())
    monkeypatch.setattr(
        project_checkout_locations, "checkout_for_project_slug", lambda _p: tmp_path
    )

    target, why = selection.resolve("platform")

    assert why == ""
    assert target is not None
    assert target.model_name == "primary"
    assert target.plan.history == ("0001_baseline",)
    assert target.databases(lambda name: name) == ["service_registry"]
    assert len(target.schema_shape_digest()) == 64
