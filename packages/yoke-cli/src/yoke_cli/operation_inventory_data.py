"""Operation tracker data rows for :mod:`yoke_cli.operation_inventory`."""

from __future__ import annotations
from typing import Tuple
from yoke_cli.operation_inventory_model import (
    PENDING,
    PERMANENT,
    REASON_NO_HANDLER_REGISTERED,
    REASON_OPERATOR_BREAK_GLASS,
    REASON_TOOL_SHAPED,
    REASON_WRAPPED_BY_YOKE_CLI,
    TOOL_CLI,
    WRAPPED,
    _Row,
    _w,
)
from yoke_cli.operation_inventory_tool_cli import TOOL_CLI_ROWS
from yoke_cli.operation_inventory_ephemeral_env import (
    WRAPPED_ROWS as EPHEMERAL_ENV_WRAPPED_ROWS,
)
from yoke_cli.operation_inventory_epic_ops import WRAPPED_ROWS as EPIC_OPS_WRAPPED_ROWS
from yoke_cli.operation_inventory_deployment import (
    WRAPPED_ROWS as DEPLOYMENT_WRAPPED_ROWS,
)
from yoke_cli.operation_inventory_github_actions import (
    WRAPPED_ROWS as GITHUB_ACTIONS_WRAPPED_ROWS,
)
from yoke_cli.operation_inventory_permanent import PERMANENT_ROWS
from yoke_cli.operation_inventory_product_surfaces import (
    WRAPPED_ROWS as PRODUCT_SURFACE_WRAPPED_ROWS,
)
from yoke_cli.operation_inventory_workflows import WRAPPED_ROWS as WORKFLOW_WRAPPED_ROWS
from yoke_cli.operation_inventory_shepherd_qa_writes import (
    WRAPPED_ROWS as SHEPHERD_QA_WRITE_ROWS,
)
from yoke_cli.operation_inventory_strategy_event import (
    WRAPPED_ROWS as STRATEGY_EVENT_WRAPPED_ROWS,
)

WRAPPED_ROWS: Tuple[_Row, ...] = (
    # Baseline wrapped item and claim operations.
    # Idea-intake create over the function-call surface (works on https);
    # replaces the local-only `db_router items add` fallback.
    _w("yoke items create", "items.create"),
    _w("yoke items progress-log append", "items.progress_log"),
    _w("yoke items github-sync", "items.github_sync"),
    _w("yoke items structured-field replace", "items.structured_field"),
    _w("yoke claims work acquire", "claims.work"),
    _w("yoke claims work release", "claims.work"),
    _w("yoke claims path register", "claims.path"),
    _w("yoke claims path widen", "claims.path"),
    _w("yoke claims path amend", "claims.path"),
    _w("yoke claims path override", "claims.path"),
    _w("yoke events query", "events.query"),
    _w("yoke lifecycle transition", "lifecycle"),
    _w("yoke lifecycle repair-status", "lifecycle"),
    _w("yoke lifecycle skip record-recoverable-substrate", "lifecycle"),
    _w("yoke ouroboros field-note append", "ouroboros"),
    _w("yoke ouroboros field-note list", "ouroboros"),
    _w("yoke ouroboros field-note get", "ouroboros"),
    # items_scalar.
    _w("yoke items scalar update", "items.scalar"),
    # items_merge_provenance: operator repair for a terminal item's unset
    # merged_at, the one sanctioned exception to terminal immutability.
    _w(
        "yoke items merge-provenance operator-correct",
        "items.merge_provenance",
    ),
    # items.section + items.structured_field additives.
    _w("yoke items section upsert", "items.section"),
    _w("yoke items section get", "items.section"),
    _w("yoke items section delete", "items.section"),
    _w("yoke items structured-field append-addendum", "items.structured_field"),
    _w("yoke items structured-field section-upsert", "items.structured_field"),
    _w("yoke items structured-field section-append", "items.structured_field"),
    # claims_read.
    _w("yoke claims work holder-get", "claims.work"),
    _w("yoke claims work holder-list", "claims.work"),
    # Intuitive alias for holder-get accepting --item or positional. Routes to
    # the same claims.work.holder_get function id.
    _w("yoke claims work current", "claims.work"),
    # Intuitive alias for holder-get reached for as post-release claim
    # verification. Same claims.work.holder_get id.
    _w("yoke claims work status", "claims.work"),
    _w("yoke path-claims conflicts list", "path_claims"),
    # db_claim.
    _w("yoke db-claim amend", "db_claim"),
    _w("yoke db-claim prose-check", "db_claim"),
    _w("yoke db read", "raw.sql"),
    _w("yoke sessions begin", "sessions"),
    _w("yoke sessions list", "sessions"),
    _w("yoke sessions touch", "sessions"),
    _w("yoke sessions checkpoint", "sessions"),
    _w("yoke sessions checkpoint-read", "sessions"),
    _w("yoke sessions offer", "sessions"),
    _w("yoke sessions ownership-guard", "sessions"),
    _w("yoke sessions end-if-empty", "sessions"),
    _w("yoke sessions reclaim-stale", "sessions"),
    *WORKFLOW_WRAPPED_ROWS,
    *PRODUCT_SURFACE_WRAPPED_ROWS,
    _w("yoke charge schedule", "charge"),
    _w("yoke frontier list", "frontier"),
    _w("yoke board rebuild", "board"),
    _w("yoke board data get", "board"),
    _w("yoke hook evaluate", "hook"),
    *EPIC_OPS_WRAPPED_ROWS,
    # qa writes.
    _w("yoke qa requirement update", "qa.requirement"),
    _w("yoke qa run record-verdict", "qa.run"),
    # Browser-QA DB legs: the orchestrator's reads/writes as dispatcher ids so
    # the flow works over https from external projects.
    _w("yoke qa browser-context get", "qa.browser"),
    _w("yoke qa run add", "qa.run"),
    _w("yoke qa run complete", "qa.run"),
    _w("yoke qa artifact add", "qa.artifact"),
    _w("yoke qa artifact presign", "qa.artifact"),
    # dispatcher-backed qa CRUD conversion: requirement reads + item-attached
    # creation + run list + the gate-entry summary. The db_router gate-summary
    # leg was checkout-shaped and broke over https; qa.gate_summary.run is the
    # dispatcher-backed fix.
    _w("yoke qa requirement list", "qa.requirement"),
    _w("yoke qa requirement get", "qa.requirement"),
    _w("yoke qa requirement add", "qa.requirement"),
    _w("yoke qa requirement add-batch", "qa.requirement"),
    _w("yoke qa run list", "qa.run"),
    _w("yoke qa run get", "qa.run"),
    _w("yoke qa gate-summary", "qa"),
    # doctor + projects + project_structure.
    _w("yoke doctor run", "doctor"),
    _w("yoke doctor last-run get", "doctor"),
    *DEPLOYMENT_WRAPPED_ROWS,
    _w("yoke projects get", "projects"),
    _w("yoke projects list", "projects"),
    _w("yoke projects resolve-by-github-repo", "projects"),
    _w("yoke projects create", "projects"),
    _w("yoke projects update", "projects"),
    _w("yoke projects capability has", "projects.capability"),
    _w("yoke projects capabilities list", "projects.capability"),
    _w("yoke projects capability-settings get", "projects.capability_settings"),
    _w("yoke projects capability-settings set", "projects.capability_settings"),
    _w("yoke projects capability-settings merge", "projects.capability_settings"),
    _w("yoke projects capability-settings remove", "projects.capability_settings"),
    _w("yoke projects environment-settings get", "projects.environment_settings"),
    _w("yoke projects environment-settings merge", "projects.environment_settings"),
    _w("yoke projects infrastructure list", "projects.infrastructure"),
    _w("yoke projects site create", "projects.infrastructure"),
    _w("yoke projects environment create", "projects.infrastructure"),
    _w("yoke projects pulumi-state migrate", "projects.pulumi_state"),
    _w("yoke projects pulumi-state checkpoint-import", "projects.pulumi_state"),
    _w("yoke projects pulumi-stack-config get", "projects.pulumi_stack_config"),
    _w("yoke projects capability-secret set", "projects.capability"),
    _w("yoke projects capability secret set", "projects.capability"),
    _w("yoke projects github-binding bind", "projects.github_binding"),
    _w("yoke projects github-binding unbind", "projects.github_binding"),
    _w("yoke projects github-binding status", "projects.github_binding"),
    _w("yoke projects github-sync-mode repair", "projects.github_sync_mode"),
    # checkout→project identity for the strategize/feed preambles — works over
    # https and from any cwd.
    _w("yoke projects checkout-context", "projects"),
    _w("yoke organizations get", "organizations"),
    # Sign-in admission admin: invites, identity links, auto-join domain.
    _w("yoke identity invite create", "identity.invite"),
    _w("yoke identity invite list", "identity.invite"),
    _w("yoke identity invite revoke", "identity.invite"),
    _w("yoke identity link set", "identity.link"),
    _w("yoke identity autojoin set", "identity.autojoin"),
    _w("yoke project-structure patch apply", "project_structure"),
    _w("yoke project-structure get", "project_structure"),
    _w(
        "yoke project-structure deploy-defaults get",
        "project_structure.deploy_defaults",
    ),
    *GITHUB_ACTIONS_WRAPPED_ROWS,
    # Per-project DB-authoritative strategy docs; each project's
    # .yoke/strategy/ is a gitignored rendered view written only by
    # `yoke strategy render` (operator edits back via `yoke strategy ingest`
    # CAS, new slugs via `doc create`, roster top-up via `seed-defaults`).
    _w("yoke strategy doc list", "strategy"),
    _w("yoke strategy doc get", "strategy"),
    _w("yoke strategy doc create", "strategy"),
    _w("yoke strategy doc replace", "strategy"),
    _w("yoke strategy doc archive", "strategy"),
    _w("yoke strategy doc unarchive", "strategy"),
    _w("yoke strategy render", "strategy"),
    _w("yoke strategy ingest", "strategy"),
    _w("yoke strategy seed-defaults", "strategy"),
    # PR-create was the last bearer-token GitHub admin surface without a wrapper
    # (repo-level github family, not github_actions).
    _w("yoke github pr create", "github"),
    _w("yoke github merge-queue apply", "github"),
    _w("yoke release-pin record", "release_pin"),
    _w("yoke onboard checklist", "onboard"),
    _w("yoke onboard checklist init", "onboard"),
    _w("yoke project snapshot sync", "project.snapshot"),
    _w("yoke packs list", "packs"),
    # cross-family-reader: cross-family reader ids — events forensics, path-claim
    # projections, ouroboros curate-loop readers, backlog listing/search,
    # dependency graph. All reads work over https from any cwd.
    _w("yoke events tail", "events"),
    _w("yoke events count", "events"),
    _w("yoke events anomalies", "events"),
    _w("yoke claims path list", "claims.path"),
    _w("yoke claims path get", "claims.path"),
    _w("yoke claims path coordination-decision-build", "claims.path"),
    # Readiness/path-claim dispatcher wrappers.
    _w("yoke readiness check", "readiness"),
    _w("yoke readiness prd-validate", "readiness"),
    _w("yoke readiness repair-stale-count", "readiness"),
    _w("yoke readiness repair-claim-coverage", "readiness"),
    _w("yoke claims path required-gate", "claims.path"),
    _w("yoke claims path activation-run", "claims.path"),
    _w("yoke ouroboros entry list", "ouroboros"),
    _w("yoke ouroboros entry get", "ouroboros"),
    _w("yoke items list", "items.read"),
    _w("yoke items search", "items.read"),
    _w("yoke shepherd dependency-list", "shepherd"),
    *SHEPHERD_QA_WRITE_ROWS,
    *STRATEGY_EVENT_WRAPPED_ROWS,
    *EPHEMERAL_ENV_WRAPPED_ROWS,
)


PENDING_ROWS: Tuple[_Row, ...] = (
    # qa family: fully converted. Reads/creation/gate-summary registered
    # by the dispatcher-backed qa CRUD slice (wrapped rows above).
    # events read family: `events list` was dispositioned as covered by
    # the registered `events.query.run` (its request model carries every
    # list filter incl. --current-episode); tail/count/anomalies are
    # wrapped above. The db_router forms remain operator-debug fallbacks.
    # deployment_runs / deployment_flows: fully dispatcher-backed.
)
__all__ = [
    "_Row",
    "WRAPPED",
    "TOOL_CLI",
    "PERMANENT",
    "PENDING",
    "REASON_WRAPPED_BY_YOKE_CLI",
    "REASON_OPERATOR_BREAK_GLASS",
    "REASON_TOOL_SHAPED",
    "REASON_NO_HANDLER_REGISTERED",
    "WRAPPED_ROWS",
    "TOOL_CLI_ROWS",
    "PERMANENT_ROWS",
    "PENDING_ROWS",
]
