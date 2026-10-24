"""The one setup step graph both setup shells compose.

``SETUP_FLOWS`` lists the decision-graph mixins in method-resolution order.
:class:`onboard_wizard_app.OnboardWizardApp` composes them under Textual and
:class:`setup_agent_shell.AgentSetup` composes them headless, so the wizard and
agent mode walk the same steps. ``init_setup_state`` sets the shared answer and
progress state both shells start from.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_project
from yoke_cli.config.onboard_wizard import (
    WizardDefaults,
    WizardResult,
    default_config_path,
)
from yoke_cli.config.onboard_wizard_flow import WizardFlow
from yoke_cli.config.onboard_wizard_flow_apply import ApplyFlow
from yoke_cli.config.onboard_wizard_flow_board_art import BoardArtFlow
from yoke_cli.config.onboard_wizard_flow_clone import CloneFlow
from yoke_cli.config.onboard_wizard_flow_connect import (
    ConnectFlow,
    HostedMachineConnectFlow,
)
from yoke_cli.config.onboard_wizard_flow_destination import DestinationFlow
from yoke_cli.config.onboard_wizard_flow_dev import DevFlow
from yoke_cli.config.onboard_wizard_flow_github import MachineGithubFlow
from yoke_cli.config.onboard_wizard_flow_hosting import HostingFlow
from yoke_cli.config.onboard_wizard_flow_project_git import ProjectGitFlow
from yoke_cli.config.onboard_wizard_flow_publish import PublishFlow
from yoke_cli.config.onboard_wizard_flow_publish_manual import ManualPublishFlow
from yoke_cli.config.onboard_wizard_path import PathFlow
from yoke_cli.config.onboard_wizard_state import _View
from yoke_cli.config.setup_run_facts import RunFacts
from yoke_cli.config.onboard_wizard_stored_connection import StoredConnectionHydration
from yoke_cli.config.onboard_wizard_view_helpers import ViewHelpers
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT_LABEL

SETUP_FLOWS: tuple[type, ...] = (
    PathFlow,
    DestinationFlow,
    HostedMachineConnectFlow,
    ConnectFlow,
    MachineGithubFlow,
    ProjectGitFlow,
    WizardFlow,
    ApplyFlow,
    CloneFlow,
    DevFlow,
    ManualPublishFlow,
    PublishFlow,
    HostingFlow,
    BoardArtFlow,
    StoredConnectionHydration,
    ViewHelpers,
)


def init_setup_state(
    shell: Any,
    *,
    defaults: WizardDefaults,
    apply_report: Callable[..., Any],
    run_facts: RunFacts | None = None,
) -> None:
    """Seed the answers, presets and progress state every setup shell reads.

    ``run_facts`` carries what earlier calls of this run already did; the
    wizard runs in one process and starts with none.
    """
    shell._apply_report = apply_report
    shell._run_facts = run_facts if run_facts is not None else RunFacts()
    shell.cancelled = False
    shell.exit_code = 0
    shell.last_error = None
    shell.failed_step = None
    shell.report_path = None
    shell.resume_command = None
    shell._stored_yoke_token_available = False
    shell._stored_yoke_attempted = False
    shell._stored_github_attempted = False
    shell._stored_machine_github_api_url = None
    shell._api_url_preset = bool(defaults.api_url)
    shell._stored_project_attempted = False
    shell._connection_status_line = None
    shell._github_success_details = False
    shell._apply_failure_details = False
    shell._stored_project_checkouts: list[machine_config.ConfiguredProject] = []
    shell._pending_stored_project_checkout = None
    shell._project_mode_preset = defaults.project_mode is not None
    shell._publication_destination_preset = defaults.project_clone_outcome
    shell._project_preset_attempted = False
    shell._preset_dev_checkout = (
        defaults.project_checkout
        if defaults.project_mode == onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE
        else None
    )
    # Apply runs as a worker: ``_applying`` guards quitting mid-mutation;
    # ``_apply_steps`` is the live step model; ``_review_plan`` is the
    # previewed plan the Applying screen renders from.
    shell._applying = False
    shell._apply_steps: list[dict[str, Any]] = []
    shell._review_plan: dict[str, Any] = {}
    shell._review_problems: list[str] = []
    shell._review_notes: list[str] = []
    shell._resume_run_id = None
    shell._resume_payload = None
    # A destination preset (CLI flags, the destination env override, or a
    # resumed run) skips the picker; the Account rail label follows the
    # routed destination on every body swap.
    shell._destination_preset = defaults.destination is not None
    shell._account_step_label = STEP_CONNECT_LABEL
    shell.result = WizardResult(
        config_path=default_config_path(defaults.config_path),
        env_name=(defaults.env_name or onboard_destinations.DEFAULT_SIGN_IN_ENV),
        api_url=(defaults.api_url or ""),
        destination=(defaults.destination or onboard_destinations.DEFAULT_DESTINATION),
        token=defaults.token,
        token_file=defaults.token_file,
        mode=(defaults.mode or "quick"),
        apply=defaults.apply,
        harness_posture=defaults.harness_posture,
        project_mode=(
            defaults.project_mode or onboard_project.PROJECT_MODE_MACHINE_ONLY
        ),
        project_checkout=defaults.project_checkout,
    )
    shell._hydrate_stored_credentials(defaults)
    shell._post_install = defaults.post_install
    shell._history: list[_View] = []
    shell._checking = False
    shell._checking_blocks_quit = False
    # login -> github_publish.RepoOwner for the chosen publish owner picker.
    shell._owner_lookup: dict[str, Any] = {}


__all__ = ["SETUP_FLOWS", "init_setup_state"]
