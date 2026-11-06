"""Offer the restored universe's projects before creating a new one."""

from yoke_cli.config import existing_project_lookup, onboard_project
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import onboard_input_validation as validation
from yoke_contracts.onboard_destinations import DESTINATION_LOCAL
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT
from yoke_cli.config.setup_prompt import SelectionRow


def offer(shell) -> None:
    shell._restored_projects_offered = True
    rows = [
        SelectionRow(
            str(row["id"]),
            str(row.get("name") or row["slug"]),
            f"restored project: {row['slug']}",
        )
        for row in shell._restored_projects
    ]
    rows.extend(
        [
            SelectionRow("other", "Choose another project", "show all project options"),
            SelectionRow("none", "Don't set up a project now", "just the machine"),
        ]
    )
    shell._goto(
        shell._selection_view(
            "project.restored",
            STEP_PROJECT,
            "Your backup's projects are ready.",
            "Choose a project to connect its code on this machine. The backup carries "
            "the project data; it does not copy your code folders.",
            rows,
            lambda choice: _selected(shell, choice),
        )
    )


def _selected(shell, choice) -> None:
    if choice == "other":
        shell._goto_project_mode()
        return
    if choice == "none":
        shell._on_project_mode(onboard_project.PROJECT_MODE_MACHINE_ONLY)
        return

    def lookup():
        if shell.result.destination == DESTINATION_LOCAL:
            return existing_project_lookup.find_local_by_project_id(
                config_path=shell.result.config_path, project_id=int(choice)
            )
        return existing_project_lookup.find_by_project_id(
            api_url=shell.result.api_url,
            token=shell._yoke_token_for_project_lookup(),
            project_id=int(choice),
        )

    shell._run_checking(
        step=STEP_PROJECT,
        title="Reading the restored project.",
        message="Checking its saved identity and repository.",
        work=lookup,
        on_success=lambda project: _checkout(shell, project),
        on_error=lambda exc: shell._goto_existing_project_lookup_error(
            exc, retry=lambda: _selected(shell, choice)
        ),
        group="onboard-restored-project",
    )


def _checkout(shell, project) -> None:
    def selected(value):
        steps.reset_project_fields(shell.result)
        shell.result.project_mode = onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
        shell.result.project_checkout = value
        shell._run_checking(
            step=STEP_PROJECT,
            title="Checking project tools.",
            message="Checking Git before connecting this checkout.",
            work=_require_git,
            on_success=lambda _: shell._after_existing_project_lookup(project),
            on_error=lambda exc: shell._goto_existing_project_lookup_error(
                exc, retry=lambda: _checkout(shell, project)
            ),
            group="onboard-restored-checkout",
        )

    shell._goto_input(
        "project.restored_checkout",
        STEP_PROJECT,
        f"Where is {project.name}'s code?",
        "Choose its local checkout. Your restored project data stays in Yoke.",
        placeholder=f"~/code/{project.slug}",
        on_done=selected,
        validate=validation.validate_create_target_folder,
    )


def _require_git():
    from yoke_cli.config.project_git_prerequisite import require_git_available

    return require_git_available()
