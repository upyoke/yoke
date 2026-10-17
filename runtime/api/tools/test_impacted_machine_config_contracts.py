"""Config contract consumers stay selected when broad reachability is deferred."""

from pathlib import Path

import pytest

from yoke_core.tools._impacted_machine_config_contracts import MACHINE_CONFIG_CONTRACTS
from yoke_core.tools.impacted_tests import build_import_index, select


MISSED_CONSUMERS = (
    "runtime/api/domain/test_runtime_settings.py",
    "runtime/api/domain/test_path_claim_active_claim_lookup.py",
    "runtime/api/test_advance_path_claim_activation.py",
    "runtime/api/domain/test_project_install_checkout_identity.py",
    "runtime/api/cli/test_db_router_connected_retired.py",
    "runtime/api/cli/test_onboard_machine_setup.py",
    "runtime/api/cli/test_hosted_machine_authorization_identity.py",
)


@pytest.mark.parametrize("source", sorted(MACHINE_CONFIG_CONTRACTS[0][1]))
def test_config_consumers_survive_bounded_deferral(tmp_path: Path, source: str):
    # The consumers intentionally have no import edge to the changed source.
    # A non-Python path forces full coverage to be deferred by bounded mode.
    for name in (source, *MISSED_CONSUMERS):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n", encoding="utf-8")
    for number in range(100):
        path = tmp_path / "runtime/api" / f"test_unrelated_{number}.py"
        path.write_text("VALUE = 1\n", encoding="utf-8")

    index = build_import_index(tmp_path)
    selected = select([source, "docs/public/cli/machine-config.md"], index, bounded=True)

    assert selected.bounded_deferral
    assert set(MISSED_CONSUMERS) <= set(selected.files)
    assert "runtime/api/test_unrelated_0.py" not in selected.files
    assert any(
        token == f"machine_config_selection_and_ownership:{source}"
        for token in selected.widening_triggers
    )


def test_unrelated_edit_does_not_select_config_consumers(tmp_path: Path):
    for name in ("runtime/api/unrelated.py", *MISSED_CONSUMERS):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n", encoding="utf-8")
    selected = select(["runtime/api/unrelated.py"], build_import_index(tmp_path))
    assert not set(MISSED_CONSUMERS).intersection(selected.files)
