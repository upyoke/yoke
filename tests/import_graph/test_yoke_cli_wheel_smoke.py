"""Installed product scenarios share one wheels-only session environment."""

import json
from zipfile import ZipFile

import pytest

from tests.import_graph import (
    wheel_smoke_cli,
    wheel_smoke_github_machine,
    wheel_smoke_setup,
    wheel_smoke_checklist,
    wheel_smoke_project_install,
    wheel_smoke_project_onboarding,
    wheel_smoke_field_note,
    wheel_smoke_https_certificate,
    wheel_smoke_preflight,
)


@pytest.mark.parametrize(
    "scenario",
    [
        wheel_smoke_cli,
        wheel_smoke_github_machine,
        wheel_smoke_setup,
        wheel_smoke_checklist,
        wheel_smoke_project_install,
        wheel_smoke_project_onboarding,
        wheel_smoke_field_note,
        wheel_smoke_https_certificate,
        wheel_smoke_preflight,
    ],
    ids=[
        "cli",
        "github_machine",
        "setup",
        "checklist",
        "project_install",
        "project_onboarding",
        "field_note",
        "https_certificate",
        "preflight",
    ],
)
def test_installed_product_scenario(
    scenario,
    tmp_path,
    product_wheelhouse,
    product_venv,
):
    scenario.smoke(
        tmp_path=tmp_path,
        product_wheelhouse=product_wheelhouse,
        product_venv=product_venv,
    )


def test_machine_qa_assets_ship_without_a_pack(product_wheelhouse):
    core = next(product_wheelhouse.glob("yoke_core-*.whl"))
    harness = next(product_wheelhouse.glob("yoke_harness-*.whl"))
    with ZipFile(core) as wheel:
        cases = json.loads(
            wheel.read("yoke_core/domain/installer_exploration_cases.json")
        )
        assert [(case["case_key"], case["method_id"]) for case in cases] == [
            ("installer-exploration", "exploratory-mission")
        ]
        assert not any("packs/machine-qa/" in name for name in wheel.namelist())
    with ZipFile(harness) as wheel:
        for name in ("provision_linux_desktop", "provision_windows_wsl_desktop"):
            assert wheel.read(f"yoke_harness/host_provisioning/{name}.py")
