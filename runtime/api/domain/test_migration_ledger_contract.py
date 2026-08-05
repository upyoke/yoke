"""What a declared migration ledger must be able to answer.

Each refusal here corresponds to a way a project can satisfy every
authoring gate and still apply migrations that silently skip entries, or
roll back past a destructive entry and still serve.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import migration_ledger_contract as contract
from yoke_core.domain.migration_model_capability_validation import (
    MigrationModelCapabilityError,
)

_VALID = {
    "table": "applied_migrations",
    "entry_column": "migration_name",
    "semantics": contract.MEMBERSHIP,
    "serving_floor_column": "minimum_serving_version",
}


def test_a_membership_ledger_with_serving_floor_parses():
    parsed = contract.parse(_VALID)
    assert parsed.table == "applied_migrations"
    assert parsed.entry_column == "migration_name"
    assert parsed.semantics == contract.MEMBERSHIP
    assert parsed.records_serving_floor
    assert parsed.serving_floor_column == "minimum_serving_version"


def test_a_missing_serving_floor_column_is_refused():
    """Membership alone cannot stop a rolled-back build from serving."""
    incomplete = {k: v for k, v in _VALID.items() if k != "serving_floor_column"}
    with pytest.raises(contract.LedgerContractError) as excinfo:
        contract.parse(incomplete)
    assert "serving_floor_column" in str(excinfo.value)


def test_a_missing_declaration_is_refused_rather_than_defaulted():
    """Supplying a default would reintroduce the unchecked assumption."""
    with pytest.raises(contract.LedgerContractError) as excinfo:
        contract.parse(None)
    assert "declares no ledger" in str(excinfo.value)


@pytest.mark.parametrize("key", contract.REQUIRED_KEYS)
def test_each_required_key_is_named_when_missing(key):
    incomplete = {k: v for k, v in _VALID.items() if k != key}
    with pytest.raises(contract.LedgerContractError) as excinfo:
        contract.parse(incomplete)
    assert key in str(excinfo.value)


def test_threshold_semantics_are_refused_with_the_three_losses_named():
    """Refused outright, not warned about.

    A warning would leave the unsound reader in place while implying it
    had been reviewed.
    """
    with pytest.raises(contract.LedgerContractError) as excinfo:
        contract.parse({**_VALID, "semantics": contract.THRESHOLD})
    message = str(excinfo.value)
    assert "skipped entry" in message
    assert "rollback" in message
    assert "out-of-order" in message


def test_unknown_semantics_are_refused():
    with pytest.raises(contract.LedgerContractError):
        contract.parse({**_VALID, "semantics": "whatever"})


def test_pending_is_membership_not_a_comparison():
    """A gap below the highest applied entry is still pending.

    This is the case a high-water mark loses permanently.
    """
    history = ["0001_a", "0002_b", "0003_c", "0004_d"]
    pending = contract.pending_entries(history, ["0001_a", "0002_b", "0004_d"])
    assert pending == ["0003_c"]


def test_pending_preserves_history_order():
    history = ["0001_a", "0002_b", "0003_c"]
    assert contract.pending_entries(history, []) == history


def test_an_entry_applied_out_of_order_is_not_pending_again():
    history = ["0001_a", "0002_b"]
    assert contract.pending_entries(history, ["0002_b", "0001_a"]) == []


def test_newer_applied_entries_are_a_valid_rollback_shape():
    outside = contract.applied_entries_outside_history(
        ["0001_a"], ["0001_a", "0009_from_newer_artifact"],
    )
    assert outside == ["0009_from_newer_artifact"]


def test_an_agreeing_ledger_has_no_entries_outside_history():
    assert contract.applied_entries_outside_history(
        ["0001_a"], ["0001_a"],
    ) == []


def test_the_runner_helper_raises_the_callers_error_type():
    """The validator's own exception type survives without a back-import."""
    with pytest.raises(MigrationModelCapabilityError) as excinfo:
        contract.runner_config_ledger(
            {**_VALID, "semantics": contract.THRESHOLD},
            MigrationModelCapabilityError,
        )
    assert "runner.config.ledger is invalid" in str(excinfo.value)


def test_the_runner_helper_normalizes_every_field():
    normalized = contract.runner_config_ledger(
        _VALID, MigrationModelCapabilityError
    )
    assert normalized == {
        "table": "applied_migrations",
        "entry_column": "migration_name",
        "semantics": contract.MEMBERSHIP,
        "serving_floor_column": "minimum_serving_version",
    }
