"""Schema-shape coverage on fleet-preflight receipts and the release gate."""

from __future__ import annotations

import json
from types import SimpleNamespace

from yoke_core.domain import migration_preflight_receipt as receipt
from runtime.api.tools import require_fleet_migration_preflight as preflight
from runtime.api.tools import yoke_migration_fleet

_DIGEST = "a" * 64
_OTHER = "b" * 64


def _row(environment: str, entries, *, digest: str = _DIGEST) -> dict:
    envelope = {
        "event_name": receipt.EVENT_NAME,
        "context": {
            receipt.ENVIRONMENT_KEY: environment,
            receipt.PRODUCT_SHA_KEY: "abc123",
            receipt.ENTRIES_KEY: entries,
            receipt.SCHEMA_SHAPE_DIGEST_KEY: digest,
        },
    }
    return {"envelope": json.dumps(envelope)}


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
        context = receipt.receipt_context(
            "prod", "abc", ["0001_a"], schema_shape_digest=f" {_DIGEST} "
        )
        assert context[receipt.SCHEMA_SHAPE_DIGEST_KEY] == _DIGEST

    def test_a_blank_digest_is_omitted_rather_than_recorded_as_coverage(self) -> None:
        context = receipt.receipt_context("prod", "abc", ["0001_a"])
        assert receipt.SCHEMA_SHAPE_DIGEST_KEY not in context

    def test_coverage_is_the_union_across_receipts(self) -> None:
        rows = [
            _row("stage", ["0001_a"], digest=_DIGEST),
            _row("stage", [], digest=_OTHER),
        ]
        assert receipt.covered_schema_shape_digests(rows, "stage") == frozenset(
            {_DIGEST, _OTHER}
        )

    def test_a_stage_digest_is_not_production_evidence(self) -> None:
        rows = [_row("stage", ["0001_a"])]
        assert receipt.covered_schema_shape_digests(rows, "prod") == frozenset()

    def test_a_legacy_receipt_without_a_digest_covers_nothing(self) -> None:
        envelope = {
            "context": {
                receipt.ENVIRONMENT_KEY: "prod",
                receipt.ENTRIES_KEY: ["0001_a"],
            }
        }
        rows = [{"envelope": json.dumps(envelope)}]
        assert receipt.uncovered_schema_shape(_DIGEST, rows, "prod") == (_DIGEST,)

    def test_a_matching_digest_is_covered(self) -> None:
        rows = [_row("prod", ["0001_a"])]
        assert receipt.uncovered_schema_shape(_DIGEST, rows, "prod") == ()

    def test_the_refusal_names_the_digest_and_the_environment(self) -> None:
        message = receipt.schema_shape_refusal_message("prod-db-admin", _DIGEST)
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
        monkeypatch.setattr(
            preflight,
            "_query_receipts",
            lambda *_args: (
                [
                    {
                        "envelope": {
                            "context": {
                                "environment": "prod",
                                "entries": ["0005_x"],
                            }
                        }
                    }
                ],
                "",
            ),
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
        monkeypatch.setattr(
            preflight,
            "_query_receipts",
            lambda *_args: ([_row("prod", ["0005_x"])], ""),
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
