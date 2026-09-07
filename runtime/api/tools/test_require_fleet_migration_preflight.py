"""Fleet rehearsal coverage as the hosted release gate reads it.

The packaged-content half of the same gate lives in
``test_release_gate_migration_content_identity``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.tools import require_fleet_migration_preflight as preflight
from runtime.api.tools import yoke_migration_fleet


@pytest.fixture(autouse=True)
def _history_tests_treat_schema_shape_as_covered(monkeypatch):
    """History-coverage tests are not the schema-shape contract.

    Schema-shape refusal lives in ``test_schema_shape_release_gate``.
    """
    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt.uncovered_schema_shape",
        lambda *_args, **_kwargs: (),
    )


def _history(monkeypatch, *names: str) -> tuple[SimpleNamespace, ...]:
    entries = tuple(
        SimpleNamespace(name=name, content_sha256=(str(index) * 64))
        for index, name in enumerate(names, start=1)
    )
    monkeypatch.setattr(yoke_migration_fleet, "history_entries", lambda: entries)
    return entries


def _coverage(monkeypatch, covered_by_environment: dict, unreadable: str = "") -> None:
    """Stand in for each environment's own coverage document.

    Keyed by environment because that is how the store is keyed: a gate can
    only ever read the environment it asked about.
    """
    from yoke_core.domain import migration_preflight_receipt as receipt

    def read(*, project, environment, paths):
        del project, paths
        if unreadable:
            return {}, unreadable
        entries = covered_by_environment.get(environment, ())
        return (
            {receipt.entry_coverage_path(name): "20260101T000000Z" for name in entries},
            "",
        )

    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt_store.read_coverage", read
    )


def _verified(monkeypatch, count: int) -> None:
    monkeypatch.setattr(
        preflight,
        "_verify_applied_migrations",
        lambda _entries: (
            {
                "status": "verified",
                "verified_count": count,
                "mismatched_entries": [],
            },
            "",
        ),
    )


def test_refusal_recipe_records_on_the_gate_connection(monkeypatch, capsys) -> None:
    monkeypatch.setenv("YOKE_ENV", "prod")
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 0)
    _coverage(monkeypatch, {})

    assert preflight.main(["prod", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "release unsafe before tag" in refusal
    assert "yoke watch preflight -- prod-db-admin" in refusal
    assert "--engine-wheel <yoke_core-wheel-from-yoke-build-artifacts>" not in refusal
    assert "--record-receipt --product-sha <sha>" in refusal
    assert "--receipt-env prod" in refusal
    assert "source tree" in refusal


def test_refusal_recipe_requires_explicit_connection_without_ambient_env(
    monkeypatch, capsys
) -> None:
    monkeypatch.delenv("YOKE_ENV", raising=False)
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 0)
    _coverage(monkeypatch, {})

    assert preflight.main(["prod-db-admin", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "yoke watch preflight -- prod-db-admin" in refusal
    assert "--receipt-env <control-plane-connection>" in refusal


def test_receipt_coverage_uses_the_registered_environment_name(
    monkeypatch, capsys
) -> None:
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 1)
    _coverage(monkeypatch, {"prod": ("0005_x",)})

    assert preflight.main(["prod", "abc123"]) == 0

    report = capsys.readouterr().out
    assert "target environment: prod" in report
    assert "covered by a passing fleet preflight: 1 of 1" in report


def test_refusal_names_every_environment_missing_a_receipt(monkeypatch, capsys) -> None:
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 0)
    _coverage(monkeypatch, {})

    assert preflight.main(["prod", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "release unsafe before tag" in refusal
    assert "per environment" in refusal
    assert "stage-db-admin" in refusal
    assert "prod-db-admin" in refusal
    assert "yoke-build-artifacts" in refusal
    assert "commit abc123" in refusal


def test_one_environment_receipt_does_not_cover_the_other(monkeypatch, capsys) -> None:
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 1)
    _coverage(monkeypatch, {"prod": ("0005_x",)})

    assert preflight.main(["stage", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "release unsafe before tag" in refusal
    assert "stage" in refusal
    assert "does not transfer" in refusal
    assert "yoke watch preflight -- stage-db-admin" in refusal


def test_unavailable_receipt_query_is_not_reported_as_unsafe(
    monkeypatch, capsys
) -> None:
    _history(monkeypatch, "0015_entry")
    _verified(monkeypatch, 1)
    _coverage(monkeypatch, {}, unreadable="transport unavailable")

    assert preflight.main(["prod", "abc123"]) == 2

    refusal = capsys.readouterr().err
    assert "release verification unavailable before tag" in refusal
    assert "transport unavailable" in refusal
    assert "unknown rather than answered" in refusal
    assert "release unsafe" not in refusal


def test_coverage_survives_with_no_telemetry_at_all(monkeypatch, capsys) -> None:
    # The whole point of the durable store: a fleet that was rehearsed stays
    # rehearsed when every event row for it is gone.
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 1)
    _coverage(monkeypatch, {"prod": ("0005_x",), "stage": ("0005_x",)})

    def _events_must_not_be_read(*_args, **_kwargs):
        raise AssertionError("the release gate read telemetry")

    monkeypatch.setattr(preflight.subprocess, "run", _events_must_not_be_read)

    assert preflight.main(["prod", "abc123"]) == 0
    assert "covered by a passing fleet preflight: 1 of 1" in capsys.readouterr().out


def test_each_environment_is_read_from_its_own_document(monkeypatch) -> None:
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 1)
    asked: list[str] = []

    def read(*, project, environment, paths):
        del project, paths
        asked.append(environment)
        return {}, ""

    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt_store.read_coverage", read
    )

    assert preflight.main(["prod", "abc123"]) == 1
    assert sorted(asked) == ["prod", "stage"]


def test_an_environment_outside_the_release_set_is_still_read(monkeypatch) -> None:
    # A release bound for an environment the shared list does not name still
    # needs that environment's own coverage, not a neighbour's.
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 1)
    asked: list[str] = []

    def read(*, project, environment, paths):
        del project, paths
        asked.append(environment)
        return {}, ""

    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt_store.read_coverage", read
    )

    assert preflight.main(["sandbox", "abc123"]) == 1
    assert "sandbox" in asked


def test_a_denied_coverage_read_is_unavailable_rather_than_unsafe(
    monkeypatch, capsys
) -> None:
    # The deploy identity needs the project read that owns coverage; without
    # it the gate does not know, and saying "unrehearsed" would send the
    # operator to rehearse a fleet that is already clean.
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 1)
    _coverage(monkeypatch, {}, unreadable="permission_denied: items.read")

    assert preflight.main(["prod", "abc123"]) == 2

    refusal = capsys.readouterr().err
    assert "release verification unavailable before tag" in refusal
    assert "for prod" in refusal
    assert "permission_denied: items.read" in refusal
    # The refusal has to say what would clear it; otherwise the operator
    # rehearses a fleet that is already clean.
    assert "project read" in refusal
