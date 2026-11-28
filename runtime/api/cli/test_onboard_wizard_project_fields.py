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


def _details_slug(defaults) -> str:
    import pytest

    pytest.importorskip("textual")
    from yoke_cli.config import onboard_wizard_project_details as details
    from yoke_cli.config.onboard_wizard_app import OnboardWizardApp

    app = OnboardWizardApp(defaults=defaults, apply_report=lambda _: {})
    shown: list = []
    app._goto = shown.append
    details.show(app, None)
    (view,) = shown
    return next(f.initial_value for f in view.prompt.fields if f.key == "slug")


def test_interactive_details_seed_the_explicit_project_slug():
    from yoke_cli.config.onboard_wizard import WizardDefaults

    checkout = "/code/demo"
    explicit = WizardDefaults(project_checkout=checkout, project_slug="acme-qa")

    assert _details_slug(explicit) == "acme-qa"
    assert _details_slug(WizardDefaults(project_checkout=checkout)) == "demo"
