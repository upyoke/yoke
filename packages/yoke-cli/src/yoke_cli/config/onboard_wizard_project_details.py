"""Single prefilled project-details form used for new project identities."""

from __future__ import annotations

from typing import Any

from textual.widgets import Static

from yoke_cli.config import onboard_input_validation as validation
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_project_prefixes as prefixes
from yoke_cli.config.onboard_wizard_input_entry import form_field_widgets
from yoke_cli.config.onboard_wizard_step_ids import STEP_PROJECT
from yoke_cli.config.setup_prompt import SelectionRow, SetupField, SetupPrompt
from yoke_cli.config.onboard_wizard_widgets import SelectionList


def fields(
    *,
    slug: str,
    branch_from_source: str | None,
    holders: prefixes.Holders | None = None,
) -> tuple[SetupField, ...]:
    items = [
        SetupField(
            "slug",
            "Project ID",
            "my-project",
            validate=validation.validate_slug,
            initial_value=slug,
        ),
        SetupField(
            "name",
            "Display name",
            "My Project",
            validate=validation.validate_display_name,
            initial_value=slug,
        ),
    ]
    if not branch_from_source:
        items.append(
            SetupField(
                "branch",
                "Default branch",
                onboard_project.DEFAULT_NEW_REPO_BRANCH,
                validate=validation.validate_branch,
                initial_value=onboard_project.DEFAULT_NEW_REPO_BRANCH,
            )
        )

    def validate_prefix(value: str) -> str | None:
        return validation.validate_prefix(value) or prefixes.holder_problem(
            value, holders, recovery=prefixes.DETAILS_RECOVERY
        )

    items.append(
        SetupField(
            "prefix",
            "Item prefix",
            "PROJ",
            validate=validate_prefix,
            initial_value=prefixes.propose(slug, holders),
        )
    )
    return tuple(items)


CONTINUE_ROWS = (
    SelectionRow("continue", "Continue", "validate and save these project details"),
)


def prompt(
    form_fields: tuple[SetupField, ...], *, branch_from_source: str | None
) -> SetupPrompt:
    return SetupPrompt(
        key="project.details",
        step=STEP_PROJECT,
        title="Project details.",
        subtitle="Enter advances fields; Enter on the last field validates the form.",
        detail_lines=(
            (f"Default branch: {branch_from_source} (from source repository)",)
            if branch_from_source
            else ()
        ),
        choices=CONTINUE_ROWS,
        fields=form_fields,
        selected="continue",
        guidance="Each field has a suggested value; answer only the ones the "
        "person wants changed, then answer continue.",
    )


def body(details: SetupPrompt) -> list[Static]:
    widgets: list[Static] = [
        Static(details.title, classes="onboard-title"),
        Static(details.subtitle or "", classes="onboard-subtitle"),
        *(Static(line, classes="onboard-plan-line") for line in details.detail_lines),
    ]
    widgets.extend(form_field_widgets(details.fields))
    widgets.append(SelectionList(list(details.choices)))
    return widgets


def show(shell: Any, holders: prefixes.Holders | None) -> None:
    """Open the details form, its prefix default skipping ``holders``."""
    from yoke_cli.config import onboard_wizard_steps as steps
    from yoke_cli.config.onboard_wizard_state import _View

    branch = shell.result.project_source_default_branch
    form_fields = fields(
        slug=shell._project_slug_preset
        or steps.slug_from_checkout(shell.result.project_checkout),
        branch_from_source=branch,
        holders=holders,
    )
    details = prompt(form_fields, branch_from_source=branch)

    def builder() -> list[Static]:
        shell._begin_form(form_fields, on_done=shell._after_project_details)
        return body(details)

    shell._goto(
        _View(
            details,
            lambda _choice: shell._submit_pending_form(),
            builder,
            on_form=shell._after_project_details,
        )
    )


__all__ = ["CONTINUE_ROWS", "body", "fields", "prompt", "show"]
