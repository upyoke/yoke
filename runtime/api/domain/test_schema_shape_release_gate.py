"""Schema-shape coverage on fleet-preflight receipts and the release gate."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import migration_preflight_receipt as receipt
from yoke_core.domain import migration_preflight_refusal
from runtime.api.tools import require_fleet_migration_preflight as preflight
from runtime.api.tools import yoke_migration_fleet

_DIGEST = "a" * 64
_OTHER = "b" * 64


def _coverage_values(entries=(), *, digest: str = _DIGEST) -> dict:
    """The coverage leaves one rehearsal leaves on its own environment."""
    values = {
        receipt.entry_coverage_path(name): "20260101T000000Z" for name in entries
    }
    if digest:
        values[receipt.schema_shape_coverage_path(digest)] = "20260101T000000Z"
    return values


def _coverage(monkeypatch, values_by_environment: dict) -> None:
    def read(*, project, environment, paths):
        del project, paths
        return dict(values_by_environment.get(environment) or {}), ""

    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt_store.read_coverage", read
    )


def _history(monkeypatch, *names: str) -> None:
    entries = tuple(
        SimpleNamespace(name=name, content_sha256=(str(index) * 64))
        for index, name in enumerate(names, start=1)
    )
    monkeypatch.setattr(yoke_migration_fleet, "history_entries", lambda: entries)


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


class TestReceiptSchemaShape:
    def test_the_digest_is_recorded_on_the_receipt(self) -> None:
        run, assignments = receipt.receipt_assignments(
            "abc", ["0001_a"], schema_shape_digest=f" {_DIGEST} "
        )
        assert assignments[receipt.schema_shape_coverage_path(_DIGEST)] == run

    def test_a_blank_digest_is_omitted_rather_than_recorded_as_coverage(self) -> None:
        _run, assignments = receipt.receipt_assignments("abc", ["0001_a"])
        assert not [
            path
            for path in assignments
            if path.startswith(receipt.SCHEMA_SHAPE_PREFIX)
        ]

    def test_coverage_is_the_union_across_rehearsals(self) -> None:
        values = {**_coverage_values(digest=_DIGEST), **_coverage_values(digest=_OTHER)}
        assert receipt.uncovered_schema_shape(_DIGEST, values) == ()
        assert receipt.uncovered_schema_shape(_OTHER, values) == ()

    def test_a_stage_digest_is_not_production_evidence(self) -> None:
        # Prod's own document is what a prod release reads, and a stage
        # rehearsal never writes there.
        assert receipt.uncovered_schema_shape(_DIGEST, {}) == (_DIGEST,)

    def test_a_rehearsal_without_a_digest_covers_no_shape(self) -> None:
        values = _coverage_values(["0001_a"], digest="")
        assert receipt.uncovered_schema_shape(_DIGEST, values) == (_DIGEST,)

    def test_a_matching_digest_is_covered(self) -> None:
        assert receipt.uncovered_schema_shape(_DIGEST, _coverage_values()) == ()

    def test_the_refusal_names_the_digest_and_the_environment(self) -> None:
        message = migration_preflight_refusal.schema_shape_refusal_message(
            "prod-db-admin", _DIGEST
        )
        assert "prod" in message
        assert _DIGEST in message
        assert "schema-shape" in message
        assert "missing column" in message


class TestReleaseGateSchemaShape:
    def test_history_coverage_without_schema_shape_is_unsafe(
        self, monkeypatch, capsys
    ) -> None:
        _history(monkeypatch, "0005_x")
        _verified(monkeypatch, 1)
        _coverage(
            monkeypatch,
            {
                "prod": _coverage_values(["0005_x"], digest=""),
                "stage": _coverage_values(["0005_x"], digest=""),
            },
        )
        monkeypatch.setattr(
            "yoke_core.domain.schema_shape_source.digest_schema_shape",
            lambda: _DIGEST,
        )

        assert preflight.main(["prod", "abc123"]) == 1
        refusal = capsys.readouterr().err
        assert "release unsafe before tag" in refusal
        assert "schema-shape" in refusal
        assert _DIGEST in refusal
        assert "yoke watch preflight -- prod-db-admin" in refusal

    def test_matching_schema_shape_and_history_pass(self, monkeypatch, capsys) -> None:
        _history(monkeypatch, "0005_x")
        _verified(monkeypatch, 1)
        _coverage(
            monkeypatch,
            {
                "prod": _coverage_values(["0005_x"]),
                "stage": _coverage_values(["0005_x"]),
            },
        )
        monkeypatch.setattr(
            "yoke_core.domain.schema_shape_source.digest_schema_shape",
            lambda: _DIGEST,
        )

        assert preflight.main(["prod", "abc123"]) == 0
        report = capsys.readouterr().out
        assert "schema-shape digest: " + _DIGEST in report
        assert "schema shape has been rehearsed" in report

    def test_unreadable_schema_shape_is_unavailable_not_unsafe(
        self, monkeypatch, capsys
    ) -> None:
        from yoke_core.domain.schema_shape_source import SchemaShapeSourceError

        def _fail() -> str:
            raise SchemaShapeSourceError("empty")

        _history(monkeypatch, "0005_x")
        _verified(monkeypatch, 1)
        monkeypatch.setattr(
            "yoke_core.domain.schema_shape_source.digest_schema_shape",
            _fail,
        )

        assert preflight.main(["prod", "abc123"]) == 2
        refusal = capsys.readouterr().err
        assert "release verification unavailable before tag" in refusal
        assert "schema-shape" in refusal
        assert "release unsafe" not in refusal
