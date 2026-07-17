"""Function-id → usage-line map for the ``yoke`` operations CLI.

Split from :mod:`yoke_cli.commands.flag_adapters` so the facade
stays under the authored-file line cap. Consumed by the entrypoint's
grouped ``--help`` text, the CLI manifest renderer, and the Atlas
integrity audit. New CLI families add one import + one line each.
"""

from __future__ import annotations

from typing import Dict

from yoke_cli.commands.adapters.claims import (
    CLAIM_PATH_REGISTER_USAGE, CLAIM_PATH_WIDEN_USAGE,
    CLAIM_WORK_ACQUIRE_USAGE, CLAIM_WORK_RELEASE_USAGE,
)
from yoke_cli.commands.adapters.organizations import ORGANIZATIONS_GET_USAGE
from yoke_cli.commands.adapters.identity import IDENTITY_USAGE
from yoke_cli.commands.adapters.claims_read import (
    CLAIM_WORK_HOLDER_GET_USAGE,
    CLAIM_WORK_HOLDER_LIST_USAGE,
    CLAIMS_PATH_GET_USAGE,
    CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE,
    CLAIMS_PATH_LIST_USAGE,
    PATH_CLAIMS_CONFLICTS_LIST_USAGE,
)
from yoke_cli.commands.adapters.config import (
    CONFIG_EXAMPLE_USAGE,
    STATUS_USAGE,
)
from yoke_cli.commands.adapters.dev import DEV_PATH_SNAPSHOT_PREWARM_USAGE, DEV_SETUP_USAGE
from yoke_cli.commands.adapters.onboard import ONBOARD_USAGE
from yoke_cli.commands.adapters.onboard_checklist import (
    ONBOARD_CHECKLIST_INIT_USAGE,
    ONBOARD_CHECKLIST_USAGE,
)
from yoke_cli.commands.adapters.project_onboard import (
    ONBOARD_PROJECT_USAGE,
)
from yoke_cli.commands.adapters.config_write import (
    AUTH_SET_USAGE, CONNECTION_REMOVE_USAGE, CONNECTION_SET_USAGE,
    ENV_USE_USAGE, PROJECT_REGISTER_USAGE,
    STAMP_PROJECT_ENV_USAGE,
)
from yoke_cli.commands.adapters.db_claim import DB_CLAIM_AMEND_USAGE
from yoke_cli.commands.adapters.db import DB_READ_USAGE
from yoke_cli.commands.adapters.doctor import (
    DOCTOR_LAST_RUN_GET_USAGE,
    DOCTOR_RUN_USAGE,
)
from yoke_cli.commands.adapters.deployment import (
    DEPLOYMENT_FLOWS_GET_USAGE,
    DEPLOYMENT_FLOWS_SET_STATUS_USAGE,
    DEPLOYMENT_FLOWS_STAGES_USAGE,
    DEPLOYMENT_RUNS_CREATE_USAGE,
    DEPLOYMENT_RUNS_APPROVE_USAGE,
    DEPLOYMENT_RUNS_GET_USAGE,
    DEPLOYMENT_RUNS_LIST_USAGE,
    DEPLOYMENT_RUNS_RESOLVE_TARGET_ENV_USAGE,
    DEPLOYMENT_RUNS_UPDATE_USAGE,
)
from yoke_cli.commands.adapters.ephemeral_env import EPHEMERAL_ENV_UPDATE_USAGE
from yoke_cli.commands.adapters.usage_epic_ops import EPIC_USAGE
from yoke_cli.commands.adapters.events import (
    EVENTS_ANOMALIES_USAGE,
    EVENTS_COUNT_USAGE,
    EVENTS_QUERY_USAGE,
    EVENTS_TAIL_USAGE,
)
from yoke_cli.commands.adapters.github import (
    GITHUB_CONNECT_USAGE, GITHUB_DISCONNECT_USAGE, GITHUB_PR_CREATE_USAGE, GITHUB_STATUS_USAGE,
)
from yoke_cli.commands.adapters.github_release import (
    GITHUB_RELEASE_CREATE_NEXT_TAG_USAGE,
)
from yoke_cli.commands.adapters.usage_github_actions import (
    USAGE_BY_FUNCTION_ID as GITHUB_ACTIONS_USAGE_BY_ID,
)
from yoke_cli.commands.adapters.hooks import HOOK_EVALUATE_USAGE
from yoke_cli.commands.adapters.install import (
    PROJECT_INSTALL_USAGE,
    PROJECT_REFRESH_USAGE,
    PROJECT_UNINSTALL_USAGE,
)
from yoke_cli.commands.adapters.project_snapshot import (
    PROJECT_SNAPSHOT_SYNC_USAGE,
)
from yoke_cli.commands.adapters.items import (
    ITEMS_GET_USAGE,
    LIFECYCLE_SKIP_RECORD_RECOVERABLE_SUBSTRATE_USAGE,
    LIFECYCLE_TRANSITION_USAGE,
    PROGRESS_LOG_USAGE,
    STRUCTURED_FIELD_USAGE,
)
from yoke_cli.commands.adapters.items_create import ITEMS_CREATE_USAGE
from yoke_cli.commands.adapters.items_scalar import ITEMS_SCALAR_UPDATE_USAGE
from yoke_cli.commands.adapters.items_section import (
    ITEMS_SECTION_DELETE_USAGE,
    ITEMS_SECTION_GET_USAGE,
    ITEMS_SECTION_UPSERT_USAGE,
    STRUCTURED_FIELD_APPEND_ADDENDUM_USAGE,
    STRUCTURED_FIELD_SECTION_APPEND_USAGE,
    STRUCTURED_FIELD_SECTION_UPSERT_USAGE,
)
from yoke_cli.commands.adapters.listing import (
    ITEMS_LIST_USAGE,
    ITEMS_SEARCH_USAGE,
    SHEPHERD_DEPENDENCY_LIST_USAGE,
)
from yoke_cli.commands.adapters.shepherd_dependency import (
    SHEPHERD_DEPENDENCY_ADD_USAGE,
    SHEPHERD_DEPENDENCY_REMOVE_USAGE,
    SHEPHERD_DEPENDENCY_UPDATE_USAGE,
)
from yoke_cli.commands.adapters.misc import (
    OUROBOROS_ENTRY_GET_USAGE,
    OUROBOROS_ENTRY_LIST_USAGE,
    OUROBOROS_FIELD_NOTE_GET_USAGE,
    OUROBOROS_FIELD_NOTE_LIST_USAGE,
    OUROBOROS_USAGE,
    SCRATCH_DISPATCH_INPUTS_USAGE,
)
from yoke_cli.commands.adapters.projects import (
    PROJECTS_CAPABILITY_HAS_USAGE,
    PROJECTS_CHECKOUT_CONTEXT_USAGE,
    PROJECTS_GET_USAGE,
    PROJECTS_LIST_USAGE,
    PROJECTS_RESOLVE_BY_GITHUB_REPO_USAGE,
    PROJECT_STRUCTURE_PATCH_APPLY_USAGE,
)
from yoke_cli.commands.adapters.projects_write import (
    PROJECTS_CREATE_USAGE,
    PROJECTS_UPDATE_USAGE,
)
from yoke_cli.commands.adapters.project_structure_read import (
    PROJECT_STRUCTURE_COMMAND_DEFINITIONS_GET_USAGE,
    PROJECT_STRUCTURE_COMMAND_DEFINITIONS_LIST_USAGE,
    PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE,
)
from yoke_cli.commands.adapters.projects_secret import (
    PROJECTS_CAPABILITY_SECRET_SET_USAGE,
)
from yoke_cli.commands.adapters.projects_capability_settings import (
    PROJECTS_CAPABILITY_SETTINGS_GET_USAGE,
    PROJECTS_CAPABILITY_SETTINGS_MERGE_USAGE,
    PROJECTS_CAPABILITY_SETTINGS_SET_USAGE,
)
from yoke_cli.commands.adapters import projects_environment_settings as _environment_settings_usage
from yoke_cli.commands.adapters.projects_pulumi_state import (
    PULUMI_STATE_CHECKPOINT_IMPORT_USAGE,
    PULUMI_STATE_MIGRATE_USAGE,
)
from yoke_cli.commands.adapters.projects_pulumi_stack_config import PULUMI_STACK_CONFIG_GET_USAGE
from yoke_cli.commands.adapters.project_github_binding import (
    PROJECTS_GITHUB_BINDING_BIND_USAGE, PROJECTS_GITHUB_BINDING_STATUS_USAGE, PROJECTS_GITHUB_BINDING_UNBIND_USAGE, PROJECTS_GITHUB_SYNC_MODE_REPAIR_USAGE,
)
from yoke_cli.commands.adapters import strategy_event_usage as _strategy_event_usage
from yoke_cli.commands.adapters import qa as _qa_usage
from yoke_cli.commands.adapters import shepherd_writes as _shepherd_writes
from yoke_cli.commands.adapters.qa import (
    QA_REQUIREMENT_AUTO_CREATE_FOR_ITEM_USAGE,
    QA_REQUIREMENT_UPDATE_USAGE,
    QA_RUN_RECORD_VERDICT_USAGE,
)
from yoke_cli.commands.adapters.qa_crud import (
    QA_REQUIREMENT_ADD_BATCH_USAGE,
    QA_REQUIREMENT_ADD_USAGE,
)
from yoke_cli.commands.adapters.qa_read import (
    QA_GATE_SUMMARY_USAGE,
    QA_REQUIREMENT_GET_USAGE,
    QA_REQUIREMENT_LIST_USAGE,
    QA_RUN_GET_USAGE,
    QA_RUN_LIST_USAGE,
)
from yoke_cli.commands.adapters.qa_browser import (
    QA_ARTIFACT_ADD_USAGE,
    QA_ARTIFACT_PRESIGN_USAGE,
    QA_BROWSER_CONTEXT_GET_USAGE,
    QA_RUN_ADD_USAGE,
    QA_RUN_COMPLETE_USAGE,
    QA_SCREENSHOT_EVIDENCE_PENDING_COUNT_USAGE,
    QA_SCREENSHOT_EVIDENCE_SATISFY_USAGE,
)
from yoke_cli.commands.adapters.board import BOARD_REBUILD_USAGE
from yoke_cli.commands.adapters.render import (
    AGENTS_RENDER_CHECK_USAGE,
    AGENTS_RENDER_USAGE,
    BOARD_DATA_GET_USAGE,
    PACKETS_CHECK_USAGE,
    PACKETS_RENDER_USAGE,
)
from yoke_cli.commands.adapters.usage_readiness import READINESS_USAGE_BY_ID
from yoke_cli.commands.adapters.strategy import (
    STRATEGY_DOC_ARCHIVE_USAGE,
    STRATEGY_DOC_GET_USAGE,
    STRATEGY_DOC_LIST_USAGE,
    STRATEGY_DOC_REPLACE_USAGE,
    STRATEGY_DOC_UNARCHIVE_USAGE,
)
from yoke_cli.commands.adapters.strategy_create import (
    STRATEGY_DOC_CREATE_USAGE,
)
from yoke_cli.commands.adapters.strategy_render import (
    STRATEGY_INGEST_USAGE,
    STRATEGY_RENDER_USAGE,
    STRATEGY_SEED_DEFAULTS_USAGE,
)
from yoke_cli.commands.adapters.templates import (
    TEMPLATES_FETCH_USAGE,
    TEMPLATES_LIST_USAGE,
)
from yoke_cli.commands.adapters.sessions import (
    CHARGE_SCHEDULE_USAGE,
    SESSIONS_BEGIN_USAGE,
    SESSIONS_CHECKPOINT_READ_USAGE,
    SESSIONS_CHECKPOINT_USAGE,
    SESSIONS_OFFER_USAGE,
    SESSIONS_OWNERSHIP_GUARD_USAGE,
    SESSIONS_TOUCH_USAGE,
)
from yoke_cli.commands.adapters.frontier_read import FRONTIER_LIST_USAGE
from yoke_cli.commands.adapters.sessions_read import SESSIONS_LIST_USAGE
from yoke_cli.commands.adapters.projects_capabilities_read import (
    PROJECTS_CAPABILITIES_LIST_USAGE,
)
from yoke_cli.commands.adapters.workflows_read import (
    WORKFLOWS_DEFINITION_GET_USAGE,
)

__all__ = ["ADAPTER_USAGE"]

# Function-id → usage-line map consumed by the entrypoint's grouped
# ``--help`` text. New CLI families add one line each.
ADAPTER_USAGE: Dict[str, str] = {
    "items.create": ITEMS_CREATE_USAGE,
    "items.get.run": ITEMS_GET_USAGE,
    "items.list.run": ITEMS_LIST_USAGE,
    "items.search.run": ITEMS_SEARCH_USAGE,
    "items.github_sync": "yoke items github-sync <PREFIX-N> [--session-id S] [--json]",
    "items.progress_log.append": PROGRESS_LOG_USAGE,
    "items.structured_field.replace": STRUCTURED_FIELD_USAGE,
    "items.scalar.update": ITEMS_SCALAR_UPDATE_USAGE,
    "items.section.upsert": ITEMS_SECTION_UPSERT_USAGE,
    "items.section.get": ITEMS_SECTION_GET_USAGE,
    "items.section.delete": ITEMS_SECTION_DELETE_USAGE,
    "items.structured_field.append_addendum": STRUCTURED_FIELD_APPEND_ADDENDUM_USAGE,
    "items.structured_field.section_upsert": STRUCTURED_FIELD_SECTION_UPSERT_USAGE,
    "items.structured_field.section_append": STRUCTURED_FIELD_SECTION_APPEND_USAGE,
    "claims.work.acquire": CLAIM_WORK_ACQUIRE_USAGE,
    "claims.work.release": CLAIM_WORK_RELEASE_USAGE,
    "claims.path.register": CLAIM_PATH_REGISTER_USAGE,
    "claims.path.widen": CLAIM_PATH_WIDEN_USAGE,
    "claims.path.list": CLAIMS_PATH_LIST_USAGE,
    "claims.path.get": CLAIMS_PATH_GET_USAGE,
    "claims.path.coordination_decision_build":
        CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE,
    "claims.work.holder_get": CLAIM_WORK_HOLDER_GET_USAGE,
    "claims.work.holder_list": CLAIM_WORK_HOLDER_LIST_USAGE,
    "path_claims.conflicts.list": PATH_CLAIMS_CONFLICTS_LIST_USAGE,
    "db_claim.amend": DB_CLAIM_AMEND_USAGE,
    "db.read.run": DB_READ_USAGE,
    "sessions.begin": SESSIONS_BEGIN_USAGE,
    "sessions.list": SESSIONS_LIST_USAGE,
    "workflows.definition.get": WORKFLOWS_DEFINITION_GET_USAGE,
    "sessions.touch": SESSIONS_TOUCH_USAGE,
    "sessions.checkpoint": SESSIONS_CHECKPOINT_USAGE,
    "sessions.checkpoint_read": SESSIONS_CHECKPOINT_READ_USAGE,
    "sessions.offer": SESSIONS_OFFER_USAGE,
    "sessions.ownership_guard": SESSIONS_OWNERSHIP_GUARD_USAGE,
    "charge.schedule": CHARGE_SCHEDULE_USAGE,
    "frontier.list": FRONTIER_LIST_USAGE,
    "agents.render.run": AGENTS_RENDER_USAGE,
    "agents.render.check": AGENTS_RENDER_CHECK_USAGE,
    "packets.render.run": PACKETS_RENDER_USAGE,
    "packets.check.run": PACKETS_CHECK_USAGE,
    "board.rebuild.run": BOARD_REBUILD_USAGE,
    "board.data.get": BOARD_DATA_GET_USAGE,
    **EPIC_USAGE,
    "qa.requirement.update": QA_REQUIREMENT_UPDATE_USAGE,
    "qa.requirement.auto_create_for_item":
        QA_REQUIREMENT_AUTO_CREATE_FOR_ITEM_USAGE,
    "qa.run.record_verdict": QA_RUN_RECORD_VERDICT_USAGE,
    "qa.browser_context.get": QA_BROWSER_CONTEXT_GET_USAGE,
    "qa.run.add": QA_RUN_ADD_USAGE,
    "qa.run.complete": QA_RUN_COMPLETE_USAGE,
    "qa.artifact.add": QA_ARTIFACT_ADD_USAGE,
    "qa.artifact.presign": QA_ARTIFACT_PRESIGN_USAGE,
    "qa.screenshot_evidence.pending_count":
        QA_SCREENSHOT_EVIDENCE_PENDING_COUNT_USAGE,
    "qa.screenshot_evidence.satisfy": QA_SCREENSHOT_EVIDENCE_SATISFY_USAGE,
    "qa.requirement.list": QA_REQUIREMENT_LIST_USAGE,
    "qa.requirement.get": QA_REQUIREMENT_GET_USAGE,
    "qa.requirement.add": QA_REQUIREMENT_ADD_USAGE,
    "qa.requirement.add_batch": QA_REQUIREMENT_ADD_BATCH_USAGE,
    "qa.run.list": QA_RUN_LIST_USAGE,
    "qa.run.get": QA_RUN_GET_USAGE,
    "qa.gate_summary.run": QA_GATE_SUMMARY_USAGE,
    "doctor.run.run": DOCTOR_RUN_USAGE,
    "doctor.last_run.get": DOCTOR_LAST_RUN_GET_USAGE,
    "deployment_flows.get": DEPLOYMENT_FLOWS_GET_USAGE,
    "deployment_flows.set_status": DEPLOYMENT_FLOWS_SET_STATUS_USAGE,
    "deployment_flows.stages": DEPLOYMENT_FLOWS_STAGES_USAGE,
    "deployment_runs.create": DEPLOYMENT_RUNS_CREATE_USAGE,
    "deployment_runs.approve": DEPLOYMENT_RUNS_APPROVE_USAGE,
    "deployment_runs.get": DEPLOYMENT_RUNS_GET_USAGE,
    "deployment_runs.list": DEPLOYMENT_RUNS_LIST_USAGE,
    "deployment_runs.update": DEPLOYMENT_RUNS_UPDATE_USAGE,
    "deployment_runs.resolve_target_env": DEPLOYMENT_RUNS_RESOLVE_TARGET_ENV_USAGE,
    "github.release.create_next_tag": GITHUB_RELEASE_CREATE_NEXT_TAG_USAGE,
    "ephemeral_env.update": EPHEMERAL_ENV_UPDATE_USAGE,
    "projects.get": PROJECTS_GET_USAGE,
    "projects.list": PROJECTS_LIST_USAGE,
    "projects.resolve_by_github_repo": PROJECTS_RESOLVE_BY_GITHUB_REPO_USAGE,
    "projects.create": PROJECTS_CREATE_USAGE,
    "projects.update": PROJECTS_UPDATE_USAGE,
    "projects.capability.has": PROJECTS_CAPABILITY_HAS_USAGE,
    "projects.capabilities.list": PROJECTS_CAPABILITIES_LIST_USAGE,
    "projects.capability_settings.get": PROJECTS_CAPABILITY_SETTINGS_GET_USAGE,
    "projects.capability_settings.set": PROJECTS_CAPABILITY_SETTINGS_SET_USAGE,
    "projects.capability_settings.merge": PROJECTS_CAPABILITY_SETTINGS_MERGE_USAGE,
    "projects.environment_settings.get": _environment_settings_usage.GET_USAGE,
    "projects.environment_settings.merge": _environment_settings_usage.MERGE_USAGE,
    "projects.pulumi_state.migrate": PULUMI_STATE_MIGRATE_USAGE,
    "projects.pulumi_state.checkpoint_import": (
        PULUMI_STATE_CHECKPOINT_IMPORT_USAGE
    ),
    "projects.pulumi_stack_config.get": PULUMI_STACK_CONFIG_GET_USAGE,
    "projects.capability_secret.set": PROJECTS_CAPABILITY_SECRET_SET_USAGE,
    "projects.checkout_context.run": PROJECTS_CHECKOUT_CONTEXT_USAGE,
    "projects.github_binding.bind": PROJECTS_GITHUB_BINDING_BIND_USAGE, "projects.github_binding.unbind": PROJECTS_GITHUB_BINDING_UNBIND_USAGE, "projects.github_binding.status": PROJECTS_GITHUB_BINDING_STATUS_USAGE,
    "projects.github_sync_mode.repair": PROJECTS_GITHUB_SYNC_MODE_REPAIR_USAGE,
    "organizations.get": ORGANIZATIONS_GET_USAGE,
    **IDENTITY_USAGE,
    "project_structure.patch.apply": PROJECT_STRUCTURE_PATCH_APPLY_USAGE,
    "project_structure.command_definitions.get":
        PROJECT_STRUCTURE_COMMAND_DEFINITIONS_GET_USAGE,
    "project_structure.command_definitions.list":
        PROJECT_STRUCTURE_COMMAND_DEFINITIONS_LIST_USAGE,
    "project_structure.deploy_defaults.get":
        PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE,
    "events.query.run": EVENTS_QUERY_USAGE,
    "events.tail.run": EVENTS_TAIL_USAGE,
    "events.count.run": EVENTS_COUNT_USAGE,
    "events.anomalies.run": EVENTS_ANOMALIES_USAGE,
    "shepherd.dependency_list.run": SHEPHERD_DEPENDENCY_LIST_USAGE,
    "shepherd.dependency_add.run": SHEPHERD_DEPENDENCY_ADD_USAGE,
    "shepherd.dependency_update.run": SHEPHERD_DEPENDENCY_UPDATE_USAGE,
    "shepherd.dependency_remove.run": SHEPHERD_DEPENDENCY_REMOVE_USAGE,
    "lifecycle.transition.execute": LIFECYCLE_TRANSITION_USAGE,
    "lifecycle.skip.record_recoverable_substrate":
        LIFECYCLE_SKIP_RECORD_RECOVERABLE_SUBSTRATE_USAGE,
    "ouroboros.field_note.append": OUROBOROS_USAGE,
    "ouroboros.field_note.list": OUROBOROS_FIELD_NOTE_LIST_USAGE,
    "ouroboros.field_note.get": OUROBOROS_FIELD_NOTE_GET_USAGE,
    "ouroboros.entry.list": OUROBOROS_ENTRY_LIST_USAGE,
    "ouroboros.entry.get": OUROBOROS_ENTRY_GET_USAGE,
    **GITHUB_ACTIONS_USAGE_BY_ID,
    "strategy.doc.list": STRATEGY_DOC_LIST_USAGE,
    "strategy.doc.get": STRATEGY_DOC_GET_USAGE,
    "strategy.doc.create": STRATEGY_DOC_CREATE_USAGE,
    "strategy.doc.replace": STRATEGY_DOC_REPLACE_USAGE,
    "strategy.doc.archive": STRATEGY_DOC_ARCHIVE_USAGE,
    "strategy.doc.unarchive": STRATEGY_DOC_UNARCHIVE_USAGE,
    "strategy.render.run": STRATEGY_RENDER_USAGE,
    "strategy.ingest.run": STRATEGY_INGEST_USAGE,
    "strategy.seed_defaults.run": STRATEGY_SEED_DEFAULTS_USAGE,
    "github.connect.run": GITHUB_CONNECT_USAGE,
    "github.disconnect.run": GITHUB_DISCONNECT_USAGE, "github.pr.create": GITHUB_PR_CREATE_USAGE,
    "github.status.run": GITHUB_STATUS_USAGE,
    "hook.evaluate.run": HOOK_EVALUATE_USAGE,
    "scratch.dispatch_inputs": SCRATCH_DISPATCH_INPUTS_USAGE,
    "config.example.run": CONFIG_EXAMPLE_USAGE,
    "config.stamp_project_env.run": STAMP_PROJECT_ENV_USAGE,
    "status.run": STATUS_USAGE,
    "dev.setup.run": DEV_SETUP_USAGE, "dev.path_snapshot_prewarm.run": DEV_PATH_SNAPSHOT_PREWARM_USAGE,
    "onboard.run": ONBOARD_USAGE,
    "onboard.project.run": ONBOARD_PROJECT_USAGE,
    "onboard.checklist.run": ONBOARD_CHECKLIST_USAGE,
    "onboard.checklist.init": ONBOARD_CHECKLIST_INIT_USAGE,
    "env.use.run": ENV_USE_USAGE,
    "connection.set.run": CONNECTION_SET_USAGE,
    "connection.remove.run": CONNECTION_REMOVE_USAGE,
    "auth.set.run": AUTH_SET_USAGE,
    "project.register.run": PROJECT_REGISTER_USAGE,
    "project.install.run": PROJECT_INSTALL_USAGE,
    "project.refresh.run": PROJECT_REFRESH_USAGE,
    "project.uninstall.run": PROJECT_UNINSTALL_USAGE,
    "project.snapshot.sync": PROJECT_SNAPSHOT_SYNC_USAGE,
    "templates.list.run": TEMPLATES_LIST_USAGE,
    "templates.fetch.run": TEMPLATES_FETCH_USAGE,
}
# Post-cap families export their own id -> usage maps; merge keeps one surface.
ADAPTER_USAGE.update(READINESS_USAGE_BY_ID)
ADAPTER_USAGE.update(_qa_usage.USAGE_BY_FUNCTION_ID)
ADAPTER_USAGE.update(_shepherd_writes.USAGE_BY_FUNCTION_ID)
ADAPTER_USAGE.update(_strategy_event_usage.USAGE_BY_FUNCTION_ID)
