"""Single prefilled project-details form used for new project identities."""

from __future__ import annotations

from textual.widgets import Static

from yoke_cli.config import onboard_input_validation as validation
from yoke_cli.config import onboard_project
from yoke_cli.config.onboard_wizard_input_entry import form_field_widgets
from yoke_cli.config.onboard_wizard_state import _FormField
from yoke_cli.config.onboard_wizard_widgets import SelectionList, SelectionRow


def fields(*, slug: str, branch_from_source: str | None) -> tuple[_FormField, ...]:
    items = [
        _FormField("slug", "Project ID", "my-project", validate=validation.validate_slug, initial_value=slug),
        _FormField("name", "Display name", "My Project", validate=validation.validate_display_name, initial_value=slug),
    ]
    if not branch_from_source:
        items.append(_FormField(
            "branch", "Default branch", onboard_project.DEFAULT_NEW_REPO_BRANCH,
            validate=validation.validate_branch,
            initial_value=onboard_project.DEFAULT_NEW_REPO_BRANCH,
        ))
    prefix = "".join(character for character in slug.upper() if character.isalnum())[:6]
    if len(prefix) < 2:
        prefix = "PRJ"
    items.append(_FormField(
        "prefix", "Item prefix", "PROJ", validate=validation.validate_prefix,
        initial_value=prefix,
    ))
    return tuple(items)


def body(form_fields: tuple[_FormField, ...], *, branch_from_source: str | None) -> list[Static]:
    subtitle = "Enter advances fields; Enter on the last field validates the form."
    widgets: list[Static] = [
        Static("Project details.", classes="onboard-title"),
        Static(subtitle, classes="onboard-subtitle"),
    ]
    if branch_from_source:
        widgets.append(Static(
            f"Default branch: {branch_from_source} (from source repository)",
            classes="onboard-plan-line",
        ))
    widgets.extend(form_field_widgets(form_fields))
    widgets.append(SelectionList([
        SelectionRow("continue", "Continue", "validate and save these project details"),
    ]))
    return widgets


__all__ = ["body", "fields"]
