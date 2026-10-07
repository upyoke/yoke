"""Stand in the engine model and its checked-out release for gate tests."""

from __future__ import annotations

from typing import Any, Sequence

MODEL = "primary"


def declare_engine_release(monkeypatch: Any, entries: Sequence[Any]) -> None:
    """Declare one engine-fleet model whose release carries *entries*.

    The schema digest is read when the gate asks for it, so a test that
    patches ``digest_schema_shape`` still decides what the gate sees.
    """
    from yoke_core.domain import migration_model_fleet_read as reader
    from yoke_core.domain import schema_shape_source
    from runtime.api.tools import require_fleet_migration_preflight as gate

    declared = reader.DeclaredFleets(
        models={MODEL: {"runner": {"config": {"modules_dir": "history"}}}},
        default_model=MODEL,
        fleets={MODEL: {"kind": "engine_tenants"}},
    )
    monkeypatch.setattr(reader, "read_declared", lambda _project: (declared, ""))
    monkeypatch.setattr(
        gate,
        "_release_inputs",
        lambda _model, _fleet: (
            tuple(entries),
            schema_shape_source.digest_schema_shape(),
        ),
    )
