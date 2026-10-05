"""Product-wheel CLI subprocess coverage survives bounded selection."""

from pathlib import Path

import pytest

from yoke_core.tools.impacted_tests import build_import_index, select


@pytest.mark.parametrize(
    "source",
    [
        "packages/yoke-cli/src/yoke_cli/project_install/uninstall.py",
        "packages/yoke-cli/src/yoke_cli/config/machine_uninstall.py",
        "packages/yoke-cli/src/yoke_cli/commands/adapters/project_install.py",
    ],
)
def test_project_install_wheel_smoke_survives_bounded_doc_deferral(
    tmp_path: Path,
    source: str,
) -> None:
    docs = "docs/public/install.md"
    smoke = "tests/import_graph/test_yoke_cli_project_install_wheel_smoke.py"
    for path, body in (
        (source, "VALUE = 1\n"),
        (docs, "Install and uninstall\n"),
        (smoke, "def test_product_wheel(): pass\n"),
    ):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)

    selection = select([source, docs], build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral is True
    assert smoke in selection.files
    assert f"product_cli_boundary_contract:{source}" in selection.widening_triggers
