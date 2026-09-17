"""The combined project form starts with useful, editable identity defaults."""

from yoke_cli.config.onboard_wizard_project_details import fields


def test_project_details_prefill_a_short_editable_prefix():
    values = {
        field.key: field.initial_value
        for field in fields(
            slug="notebook-app",
            branch_from_source=None,
        )
    }

    assert values == {
        "slug": "notebook-app",
        "name": "notebook-app",
        "branch": "main",
        "prefix": "NOTEBO",
    }
