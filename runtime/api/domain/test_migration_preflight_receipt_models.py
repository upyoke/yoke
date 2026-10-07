"""Fleet coverage belongs to one migration model, never to its siblings."""

from __future__ import annotations

import pytest

from yoke_core.domain import migration_preflight_receipt as receipt


def test_shared_entry_name_in_another_model_is_not_coverage() -> None:
    _run, values = receipt.receipt_assignments(
        "registry", "abc", ["0001_init"], schema_shape_digest="shape1"
    )

    assert receipt.uncovered("registry", ["0001_init"], values) == ()
    assert receipt.uncovered("primary", ["0001_init"], values) == ("0001_init",)
    assert receipt.uncovered_schema_shape("primary", "shape1", values) == ("shape1",)


def test_each_model_owns_its_own_namespace() -> None:
    assert receipt.entry_coverage_path("registry", "0001_init") == (
        "release.fleet_rehearsal.registry.entry.0001_init"
    )
    assert receipt.coverage_paths("primary", ["0001_init"], "d") == (
        "release.fleet_rehearsal.primary.entry.0001_init",
        "release.fleet_rehearsal.primary.schema_shape.d",
    )


def test_a_model_name_that_would_nest_keys_is_refused() -> None:
    with pytest.raises(receipt.ReceiptPathError, match="migration model name"):
        receipt.entry_coverage_path("bad.model", "0001_init")
