"""Installed product scenarios share one wheels-only session environment."""

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
