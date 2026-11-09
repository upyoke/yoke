"""Dynamic imports retain migration consumers in impacted selections."""

from pathlib import Path

from yoke_core.tools._impacted_import_index import build_import_index
from yoke_core.tools.impacted_tests import select


def _write(root: Path, path: str, body: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_digit_prefixed_dynamic_import_keeps_transitive_contract_test(tmp_path):
    contract = "pkg/contract.py"
    migration = "pkg/migrations/0001_settings.py"
    consumer = "runtime/api/test_settings_migration.py"
    _write(tmp_path, contract, "VALUE = 1\n")
    _write(tmp_path, migration, "from pkg.contract import VALUE\n")
    _write(
        tmp_path,
        consumer,
        'import importlib\nMIGRATION = importlib.import_module("pkg.migrations.0001_settings")\n',
    )
    index = build_import_index(tmp_path)

    for changed in (contract, migration):
        selection = select([changed], index, bounded=True)
        assert consumer in selection.files


def test_history_changes_select_the_table_driven_contract():
    from yoke_core.tools._impacted_contract_tests import contract_selection_for

    selection = contract_selection_for(
        [
            "packages/yoke-core/src/yoke_core/domain/migrations/0101_decision_request_audiences.py"
        ]
    )
    assert {
        "runtime/api/domain/test_migration_entry_contract.py",
        "runtime/api/domain/test_migration_entry_test_policy.py",
    } <= selection.tests
