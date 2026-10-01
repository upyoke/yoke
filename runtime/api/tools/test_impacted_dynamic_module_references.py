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


def test_test_machine_os_contract_selects_its_live_migration_consumer(tmp_path):
    """Copy the real imports so the regression covers their actual spelling."""
    root = Path(__file__).resolve().parents[3]
    contract = (
        "packages/yoke-contracts/src/yoke_contracts/machine_config/test_machine.py"
    )
    migration = (
        "packages/yoke-core/src/yoke_core/domain/migrations/0050_test_machine_os.py"
    )
    consumer = "runtime/api/domain/test_migration_test_machine_os.py"
    for path in (contract, migration, consumer):
        _write(tmp_path, path, (root / path).read_text(encoding="utf-8"))

    selection = select([contract], build_import_index(tmp_path), bounded=True)

    assert consumer in selection.files
