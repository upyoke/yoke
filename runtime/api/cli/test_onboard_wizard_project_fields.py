"""Public-item prefix is explicit; the wizard never derives one."""

from yoke_cli.config.onboard_wizard_project_fields import (
    PREFIX_PROMPT_SUBTITLE,
    prefix_from_slug,
)


def test_prefix_from_slug_does_not_invent_a_prefix():
    assert prefix_from_slug("notebook-app") == ""
    assert prefix_from_slug(None) == ""
    assert "does not suggest or derive" in PREFIX_PROMPT_SUBTITLE
