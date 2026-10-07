"""The pre-tag gate reads each declared model's fleet, not the engine's alone."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import migration_model_fleet_read as reader
from yoke_core.domain import migration_preflight_receipt as receipt
from runtime.api.tools import require_fleet_migration_preflight as gate

_NAMED = {
    "kind": "named_databases",
    "names": ["service_registry"],
    "converge_argv": ["svc", "init"],
    "schema_shape_sources": ["svc/schema.py"],
}


def _declare(monkeypatch, fleets: dict) -> None:
    models = {name: {"runner": {"config": {"modules_dir": "h"}}} for name in fleets}
    declared = reader.DeclaredFleets(
        models=models,
        default_model=next(iter(models)),
        fleets={name: fleet for name, fleet in fleets.items() if fleet is not None},
    )
    monkeypatch.setattr(reader, "read_declared", lambda _p: (declared, ""))
    monkeypatch.setattr(
        gate,
        "_release_inputs",
        lambda _m, _f: (
            (SimpleNamespace(name="0001_init", content_sha256="0" * 64),),
            "d",
        ),
    )


def _coverage(monkeypatch, values: dict) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt_store.read_coverage",
        lambda **_kw: (dict(values), ""),
    )


def test_fleet_none_passes_with_its_reason(monkeypatch, capsys) -> None:
    _declare(monkeypatch, {"primary": {"kind": "none", "reason": "host-local SQLite"}})

    assert gate.main(["--project", "buzz", "prod"]) == 0
    assert "host-local SQLite" in capsys.readouterr().out


def test_undeclared_fleet_is_unsafe_with_the_recipe(monkeypatch, capsys) -> None:
    _declare(monkeypatch, {"registry": None})

    assert gate.main(["--project", "platform", "prod"]) == 1
    refusal = capsys.readouterr().err
    assert "declares no fleet" in refusal
    assert "--cap-type migration_fleet" in refusal


def test_named_fleet_reads_only_its_own_model_coverage(monkeypatch, capsys) -> None:
    _declare(monkeypatch, {"registry": _NAMED})
    _, other_model = receipt.receipt_assignments(
        "primary", "abc", ["0001_init"], schema_shape_digest="d"
    )
    _coverage(monkeypatch, other_model)

    assert gate.main(["--project", "platform", "prod"]) == 1
    assert "--project platform --model registry" in capsys.readouterr().err

    _, own_model = receipt.receipt_assignments(
        "registry", "abc", ["0001_init"], schema_shape_digest="d"
    )
    _coverage(monkeypatch, own_model)
    assert gate.main(["--project", "platform", "prod"]) == 0


def test_project_is_required(capsys) -> None:
    assert gate.main(["prod"]) == 2
    assert "--project P" in capsys.readouterr().err
