"""Shared onboarding checklist contract for client and server."""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1
SCHEMA_NAME = "yoke.onboard.checklist"
OPERATION = "onboard.checklist"
OPERATION_INIT = "onboard.checklist.init"
HANDOFF_TO = "yoke onboard project"

STATUS_UNKNOWN = "unknown"
STATUS_NEEDED = "needed"
STATUS_NOT_NEEDED = "not-needed"
STATUS_DEFERRED = "deferred"
STATUS_CONFIGURED = "configured"
STATUS_VERIFIED = "verified"
STATUS_BLOCKED = "blocked"

CHECKLIST_STATUSES = (
    STATUS_UNKNOWN,
    STATUS_NEEDED,
    STATUS_NOT_NEEDED,
    STATUS_DEFERRED,
    STATUS_CONFIGURED,
    STATUS_VERIFIED,
    STATUS_BLOCKED,
)

LAYER_MACHINE = "machine"
LAYER_PROJECT = "project"
LAYER_AGENTIC = "agentic"
LAYER_CAPABILITY = "capability"
LAYER_DELIVERY = "delivery"
LAYER_VERIFICATION = "verification"

CHECKLIST_LAYERS = (
    LAYER_MACHINE,
    LAYER_PROJECT,
    LAYER_AGENTIC,
    LAYER_CAPABILITY,
    LAYER_DELIVERY,
    LAYER_VERIFICATION,
)

TERMINAL_STATUSES = (
    STATUS_NOT_NEEDED,
    STATUS_DEFERRED,
    STATUS_VERIFIED,
)

BRANCH_MACHINE_ONLY = "machine-only"
BRANCH_CREATE_REPO = "create-repo"
BRANCH_CLONE_REMOTE = "clone-remote"
BRANCH_LOCAL_CHECKOUT = "local-checkout"
BRANCH_SOURCE_DEV_ADMIN = "source-dev-admin"

BRANCHES = (
    BRANCH_MACHINE_ONLY,
    BRANCH_CREATE_REPO,
    BRANCH_CLONE_REMOTE,
    BRANCH_LOCAL_CHECKOUT,
    BRANCH_SOURCE_DEV_ADMIN,
)


@dataclass(frozen=True)
class ChecklistRowSpec:
    """Static row definition for the onboarding checklist contract."""

    row_id: str
    step: str
    title: str
    layer: str
    owner: str
    hint: str


SOURCE_DEV_ROW_ID = "source-dev-admin-branch"
SETUP_HANDOFF_ROW_ID = "setup-checklist-handoff"

ROW_SPECS = (
    ChecklistRowSpec("package-install", "1", "Package install", LAYER_MACHINE,
                     "public installer", "Install the Yoke CLI package."),
    ChecklistRowSpec("machine-profile", "2", "Machine profile", LAYER_MACHINE,
                     "yoke onboard", "Create ~/.yoke and secret storage."),
    ChecklistRowSpec("yoke-connection", "3", "Yoke connection", LAYER_MACHINE,
                     "yoke onboard", "Store API auth by secret reference."),
    ChecklistRowSpec("project-permission", "4", "Project permission",
                     LAYER_PROJECT, "yoke onboard / admin",
                     "Verify the actor can create or bind the project."),
    ChecklistRowSpec("machine-github-connection", "5",
                     "Machine GitHub connection", LAYER_MACHINE,
                     "yoke onboard", "Verify GitHub identity and repo access."),
    ChecklistRowSpec("project-source-choice", "6", "Project source choice",
                     LAYER_PROJECT, "yoke onboard",
                     "Choose create, clone, local checkout, or machine-only."),
    ChecklistRowSpec("project-identity", "7", "Project identity",
                     LAYER_PROJECT, "yoke onboard",
                     "Bind project metadata and repository identity."),
    ChecklistRowSpec("checkout-binding", "8", "Checkout binding", LAYER_PROJECT,
                     "yoke project install",
                     "Map the checkout to project identity."),
    ChecklistRowSpec("deterministic-repo-substrate", "9",
                     "Deterministic repo substrate", LAYER_PROJECT,
                     "yoke project install",
                     "Install the project-local Yoke contract."),
    ChecklistRowSpec(SOURCE_DEV_ROW_ID, "9a", "Yoke source-dev/admin branch",
                     LAYER_PROJECT, "explicit source-dev/admin setup",
                     "Only for Yoke source or explicit admin setup."),
    ChecklistRowSpec(SETUP_HANDOFF_ROW_ID, "10", "Setup checklist + handoff",
                     LAYER_AGENTIC, "yoke onboard",
                     "Produce the resumable handoff context."),
    ChecklistRowSpec("repo-survey", "11", "Repo survey", LAYER_AGENTIC,
                     HANDOFF_TO, "Ground docs, manifests, CI, and project shape."),
    ChecklistRowSpec("human-interview", "12", "Human interview", LAYER_AGENTIC,
                     HANDOFF_TO, "Resolve unknowns, deferrals, and blockers."),
    ChecklistRowSpec("documentation-context-setup", "13",
                     "Documentation/context setup", LAYER_AGENTIC,
                     HANDOFF_TO, "Create context routing and runbooks."),
    ChecklistRowSpec("strategy-setup", "14", "Strategy setup", LAYER_AGENTIC,
                     HANDOFF_TO, "Render DB-backed strategy docs."),
    ChecklistRowSpec("project-structure-setup", "15",
                     "Project Structure setup", LAYER_PROJECT,
                     HANDOFF_TO, "Capture project-wide policy rows."),
    ChecklistRowSpec("capability-setup", "16", "Capability setup",
                     LAYER_CAPABILITY, HANDOFF_TO,
                     "Configure needed capabilities and secrets."),
    ChecklistRowSpec("delivery-setup", "17", "Delivery setup", LAYER_DELIVERY,
                     HANDOFF_TO, "Configure sites, envs, flows, and automation."),
    ChecklistRowSpec("verification", "18", "Verification", LAYER_VERIFICATION,
                     "CLI + yoke onboard project",
                     "Run status, auth, command, render, and doctor checks."),
    ChecklistRowSpec("lifecycle-readiness", "19", "Lifecycle readiness",
                     LAYER_VERIFICATION, "Lifecycle",
                     "Enable first project-scoped backlog item."),
    ChecklistRowSpec("later-per-item-facts", "20", "Later per-item facts",
                     LAYER_VERIFICATION, "Lifecycle",
                     "Created when actual work starts."),
    ChecklistRowSpec("continuous-systems", "21", "Continuous systems",
                     LAYER_VERIFICATION, "All layers",
                     "Keep doctor, events, and learning active."),
)

ROW_IDS = tuple(spec.row_id for spec in ROW_SPECS)
PROJECT_ROW_IDS = tuple(
    spec.row_id for spec in ROW_SPECS
    if spec.layer != LAYER_MACHINE and spec.row_id != SETUP_HANDOFF_ROW_ID
)


__all__ = [
    "BRANCHES",
    "BRANCH_CLONE_REMOTE",
    "BRANCH_CREATE_REPO",
    "BRANCH_LOCAL_CHECKOUT",
    "BRANCH_MACHINE_ONLY",
    "BRANCH_SOURCE_DEV_ADMIN",
    "CHECKLIST_LAYERS",
    "CHECKLIST_STATUSES",
    "ChecklistRowSpec",
    "HANDOFF_TO",
    "OPERATION",
    "OPERATION_INIT",
    "PROJECT_ROW_IDS",
    "ROW_IDS",
    "ROW_SPECS",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "SETUP_HANDOFF_ROW_ID",
    "SOURCE_DEV_ROW_ID",
    "STATUS_BLOCKED",
    "STATUS_CONFIGURED",
    "STATUS_DEFERRED",
    "STATUS_NEEDED",
    "STATUS_NOT_NEEDED",
    "STATUS_UNKNOWN",
    "STATUS_VERIFIED",
    "TERMINAL_STATUSES",
]
