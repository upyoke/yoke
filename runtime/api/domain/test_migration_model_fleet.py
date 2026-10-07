"""A migration model's fleet declaration and the plan it produces."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain.migration_fleet_declared_plan import (
    DeclaredCommandError,
    declared_plan,
    run_declared,
)
from yoke_core.domain.migration_model_capability_validation import (
    MigrationModelCapabilityError,
    validate,
)
from yoke_core.domain.migration_model_fleet import (
    FLEET_NAMED_DATABASES,
    fleet_of,
    undeclared_refusal,
    validate_fleet,
)
from yoke_core.domain.schema_shape_source import (
    SchemaShapeSourceError,
    digest_declared_sources,
)
from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed

_NAMED = {
    "kind": FLEET_NAMED_DATABASES,
    "names": ["service_registry"],
    "converge_argv": ["python", "-m", "service.schema", "init"],
    "verify_argv": ["python", "-m", "service.schema", "status"],
    "schema_shape_sources": ["service/schema.py"],
}


def _capability(fleet: dict | None) -> dict:
    seed = governed_postgres_test_seed()
    if fleet is not None:
        seed["models"]["primary"]["fleet"] = fleet
    return seed


@pytest.mark.parametrize(
    "fleet",
    [
        {"kind": "engine_tenants"},
        {"kind": "none", "reason": "one database on the production host"},
        _NAMED,
    ],
)
def test_capability_accepts_each_fleet_kind(fleet: dict) -> None:
    model = validate(_capability(fleet))["models"]["primary"]
    assert fleet_of(model) == fleet


def test_capability_without_fleet_stays_valid_and_reads_as_undeclared() -> None:
    model = validate(_capability(None))["models"]["primary"]
    assert fleet_of(model) is None
    refusal = undeclared_refusal("platform", "registry")
    assert "declares no fleet" in refusal
    assert "capability-settings merge --project platform" in refusal


@pytest.mark.parametrize(
    "fleet, fragment",
    [
        ({"kind": "everything"}, "fleet.kind"),
        ({"kind": "none"}, "fleet.reason"),
        ({"kind": "engine_tenants", "names": ["x"]}, "unknown keys"),
        ({**_NAMED, "names": []}, "fleet.names"),
        ({**_NAMED, "names": ["Bad-Name"]}, "not a database name"),
        ({**_NAMED, "names": ["a", "a"]}, "must not repeat"),
        ({**_NAMED, "converge_argv": "init"}, "fleet.converge_argv"),
        ({**_NAMED, "schema_shape_sources": ["../x.py"]}, "inside the project"),
    ],
)
def test_malformed_fleet_is_refused_by_name(fleet: dict, fragment: str) -> None:
    with pytest.raises(
        MigrationModelCapabilityError, match=fragment.replace(".", r"\.")
    ):
        validate_fleet(fleet, MigrationModelCapabilityError)


def test_declared_source_digest_follows_content_and_names_missing_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "service").mkdir()
    schema = tmp_path / "service" / "schema.py"
    schema.write_text('"""Doc."""\nTABLES = {"users": "id"}\n')
    first = digest_declared_sources(tmp_path, ["service/schema.py"])
    schema.write_text('"""Reworded doc."""\nTABLES = {"users": "id"}\n')
    assert digest_declared_sources(tmp_path, ["service/schema.py"]) == first
    schema.write_text('"""Doc."""\nTABLES = {"users": "id, email"}\n')
    assert digest_declared_sources(tmp_path, ["service/schema.py"]) != first
    with pytest.raises(SchemaShapeSourceError, match="fleet.schema_shape_sources"):
        digest_declared_sources(tmp_path, ["service/missing.py"])


def _checkout(tmp_path: Path) -> Path:
    history = tmp_path / "service" / "migrations"
    history.mkdir(parents=True)
    for name in ("0001_baseline", "0002_rewrite_rows"):
        (history / f"{name}.py").write_text("def apply(conn):\n    pass\n")
    return tmp_path


class _Ledger:
    """Answers the two reads the plan makes: table presence and membership."""

    def __init__(self, applied: tuple[str, ...] | None) -> None:
        self.applied = applied
        self.rolled_back = 0

    def execute(self, sql: str, _params: tuple = ()) -> SimpleNamespace:
        if "to_regclass" in sql:
            present = None if self.applied is None else "applied_migrations"
            return SimpleNamespace(fetchone=lambda: (present,))
        return SimpleNamespace(fetchall=lambda: [(name,) for name in self.applied])

    def rollback(self) -> None:
        self.rolled_back += 1


def _plan(tmp_path: Path, fleet: dict):
    model = governed_postgres_test_seed()["models"]["primary"]
    model["runner"]["config"]["modules_dir"] = "service/migrations"
    model["runner"]["config"]["connection_env_var"] = "SERVICE_DSN"
    return declared_plan(model, fleet, _checkout(tmp_path))


def test_declared_plan_reads_history_and_declared_ledger(tmp_path: Path) -> None:
    plan = _plan(tmp_path, _NAMED)
    assert plan.history == ("0001_baseline", "0002_rewrite_rows")
    assert plan.pending_names(_Ledger(None), plan.history) == plan.history
    assert plan.pending_names(_Ledger(("0001_baseline",)), plan.history) == (
        "0002_rewrite_rows",
    )
    assert plan.load_module is None


def _probe(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_converge_runs_the_project_command_with_the_copy_bound(tmp_path: Path) -> None:
    marker = tmp_path / "converged"
    fleet = {
        **_NAMED,
        "converge_argv": _probe(
            "import os, pathlib; "
            f"pathlib.Path({str(marker)!r}).write_text(os.environ['SERVICE_DSN'])"
        ),
    }
    fleet.pop("verify_argv")
    plan = _plan(tmp_path, fleet)
    ledger = _Ledger(())

    plan.converge(ledger, "dbname=copy")

    assert marker.read_text() == "dbname=copy"
    assert ledger.rolled_back == 1
    assert plan.post_converge_validator is None


def test_failing_verify_is_a_named_verdict_with_the_dsn_redacted(
    tmp_path: Path,
) -> None:
    fleet = {
        **_NAMED,
        "verify_argv": _probe(
            "import os, sys; sys.stderr.write('not ready ' + os.environ['SERVICE_DSN']); "
            "sys.exit(1)"
        ),
    }
    plan = _plan(tmp_path, fleet)

    failure = plan.post_converge_validator(_Ledger(()), "dbname=secret-copy")

    assert failure is not None
    assert "exited 1" in failure
    assert "not ready <dsn>" in failure
    assert "secret-copy" not in failure


def test_missing_command_names_where_it_was_run(tmp_path: Path) -> None:
    with pytest.raises(DeclaredCommandError, match="could not start from"):
        run_declared(
            ["definitely-not-a-command-on-path"],
            cwd=tmp_path,
            env_var="SERVICE_DSN",
            dsn="dbname=copy",
        )
