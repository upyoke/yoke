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
    WRAPPED,
    _p,
    _Row,
    _w,
)
from yoke_cli.operation_inventory_ephemeral_env import WRAPPED_ROWS as EPHEMERAL_ENV_WRAPPED_ROWS
from yoke_cli.operation_inventory_epic_ops import WRAPPED_ROWS as EPIC_OPS_WRAPPED_ROWS
from yoke_cli.operation_inventory_github_actions import WRAPPED_ROWS as GITHUB_ACTIONS_WRAPPED_ROWS
from yoke_cli.operation_inventory_installer_local import PERMANENT_ROWS as INSTALLER_LOCAL_PERMANENT_ROWS
from yoke_cli.operation_inventory_shepherd_qa_writes import WRAPPED_ROWS as SHEPHERD_QA_WRITE_ROWS
from yoke_cli.operation_inventory_strategy_event import PERMANENT_ROWS as STRATEGY_EVENT_PERMANENT_ROWS, WRAPPED_ROWS as STRATEGY_EVENT_WRAPPED_ROWS
WRAPPED_ROWS: Tuple[_Row, ...] = (
    # Baseline wrapped item and claim operations.
    _w("yoke items get", "items.read"),
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
    _w("yoke events query", "events.query"),
    _w("yoke lifecycle transition", "lifecycle"),
    _w("yoke lifecycle skip record-recoverable-substrate", "lifecycle"),
    _w("yoke ouroboros field-note append", "ouroboros"),
    _w("yoke ouroboros field-note list", "ouroboros"),
    _w("yoke ouroboros field-note get", "ouroboros"),
    # items_scalar.
    _w("yoke items scalar update", "items.scalar"),
    # items.section + items.structured_field additives.
    _w("yoke items section upsert", "items.section"),
    _w("yoke items section get", "items.section"),
    _w("yoke items section delete", "items.section"),
    _w("yoke items structured-field append-addendum",
       "items.structured_field"),
    _w("yoke items structured-field section-upsert",
       "items.structured_field"),
    _w("yoke items structured-field section-append",
       "items.structured_field"),
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
    _w("yoke db read", "raw.sql"),
    _w("yoke sessions begin", "sessions"),
    _w("yoke sessions list", "sessions"),
    _w("yoke sessions touch", "sessions"),
    _w("yoke sessions checkpoint", "sessions"),
    _w("yoke sessions checkpoint-read", "sessions"),
    _w("yoke sessions offer", "sessions"),
    _w("yoke sessions ownership-guard", "sessions"),
    _w("yoke charge schedule", "charge"),
    # render.
    _w("yoke agents render", "agents.render"),
    _w("yoke agents render check", "agents.render"),
    _w("yoke packets render", "packets"),
    _w("yoke packets check", "packets"),
    _w("yoke board rebuild", "board"),
    _w("yoke board data get", "board"),
    _w("yoke hook evaluate", "hook"),
    *EPIC_OPS_WRAPPED_ROWS,
    # qa writes.
    _w("yoke qa requirement update", "qa.requirement"),
    _w("yoke qa requirement auto-create-for-item", "qa.requirement"),
    _w("yoke qa run record-verdict", "qa.run"),
    # Browser-QA DB legs: the orchestrator's reads/writes as dispatcher ids so
    # the flow works over https from external projects.
    _w("yoke qa browser-context get", "qa.browser"),
    _w("yoke qa run add", "qa.run"),
    _w("yoke qa run complete", "qa.run"),
    _w("yoke qa artifact add", "qa.artifact"),
    _w("yoke qa artifact presign", "qa.artifact"),
    _w("yoke qa screenshot-evidence pending-count",
       "qa.screenshot_evidence"),
    _w("yoke qa screenshot-evidence satisfy", "qa.screenshot_evidence"),
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
    # Deployment flow/run reads, run update, and the target-env resolver
    # used by usher ride the dispatcher instead of pending db_router
    # fallbacks.
    _w("yoke deployment-flows get", "deployment_flows"),
    _w("yoke deployment-flows stages", "deployment_flows"),
    _w("yoke deployment-runs get", "deployment_runs"),
    _w("yoke deployment-runs list", "deployment_runs"),
    _w("yoke deployment-runs update", "deployment_runs"),
    _w("yoke deployment-runs resolve-target-env", "deployment_runs"),
    _w("yoke projects get", "projects"),
    _w("yoke projects list", "projects"),
    _w("yoke projects resolve-by-github-repo", "projects"),
    _w("yoke projects create", "projects"),
    _w("yoke projects update", "projects"),
    _w("yoke projects capability has", "projects.capability"),
    _w("yoke projects capabilities list", "projects.capability"),
    _w("yoke projects capability-settings get", "projects.capability_settings"), _w("yoke projects capability-settings set", "projects.capability_settings"),
    _w("yoke projects capability-settings merge", "projects.capability_settings"),
    _w("yoke projects environment-settings get", "projects.environment_settings"), _w("yoke projects environment-settings merge", "projects.environment_settings"),
    _w("yoke projects capability-secret set", "projects.capability"),
    _w("yoke projects capability secret set", "projects.capability"),
    _w("yoke projects github-binding bind", "projects.github_binding"), _w("yoke projects github-binding unbind", "projects.github_binding"), _w("yoke projects github-binding status", "projects.github_binding"),
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
    _w("yoke project-structure command-definitions get", "project_structure.command_definitions"),
    _w("yoke project-structure command-definitions list", "project_structure.command_definitions"),
    _w("yoke project-structure deploy-defaults get", "project_structure.deploy_defaults"),
    *GITHUB_ACTIONS_WRAPPED_ROWS,
    # Per-project DB-authoritative strategy docs; each project's
    # .yoke/strategy/ is a gitignored local rendered view written only by
    # `yoke strategy render`, with operator edits written back via
    # `yoke strategy ingest` (CAS), brand-new slugs created by
    # `yoke strategy doc create`, and cold starts minted by
    # `yoke strategy seed-defaults`.
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
    # Project-scoped scratch path resolver for shepherd skill dispatch.
    _w("yoke scratch dispatch-inputs", "scratch"),
    # machine-config status: machine config example + local status diagnostics.
    _w("yoke config example", "config"), _w("yoke config stamp-project-env", "config"),
    _w("yoke status", "status"),
    _w("yoke onboard checklist", "onboard"),
    _w("yoke onboard checklist init", "onboard"),
    _w("yoke env use", "env"),
    _w("yoke connection set", "connection"),
    _w("yoke connection remove", "connection"),
    _w("yoke auth set", "auth"),
    _w("yoke project register", "project"),
    _w("yoke project install", "project"),
    _w("yoke project refresh", "project"),
    _w("yoke project uninstall", "project"),
    _w("yoke project snapshot sync", "project.snapshot"),
    _w("yoke templates list", "templates"),
    _w("yoke templates fetch", "templates"),
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
    *STRATEGY_EVENT_WRAPPED_ROWS, *EPHEMERAL_ENV_WRAPPED_ROWS,
)


PERMANENT_ROWS: Tuple[_Row, ...] = (
    # Coordination-lease family — operator break-glass.
    _p("python3 -m yoke_core.api.service_client coordination-lease-acquire",
       "claims.coordination_lease", REASON_OPERATOR_BREAK_GLASS),
    _p("python3 -m yoke_core.api.service_client coordination-lease-heartbeat",
       "claims.coordination_lease", REASON_OPERATOR_BREAK_GLASS),
    _p("python3 -m yoke_core.api.service_client coordination-lease-list",
       "claims.coordination_lease", REASON_OPERATOR_BREAK_GLASS),
    _p("python3 -m yoke_core.api.service_client coordination-lease-release",
       "claims.coordination_lease", REASON_OPERATOR_BREAK_GLASS),
    # claims.path operator-only paths.
    _p("python3 -m yoke_core.api.service_client path-claim-override",
       "claims.path", REASON_OPERATOR_BREAK_GLASS),
    _p("python3 -m yoke_core.cli.db_router path-claims activate",
       "claims.path", REASON_OPERATOR_BREAK_GLASS),
    _p("python3 -m yoke_core.cli.db_router path-claims amend",
       "claims.path", REASON_OPERATOR_BREAK_GLASS),
    _p("python3 -m yoke_core.cli.db_router path-claims release",
       "claims.path", REASON_OPERATOR_BREAK_GLASS),
    # Tool-shaped local git/filesystem operations — deliberately NOT
    # dispatcher function ids; routed as CLI tokens by yoke_cli.main.
    _p("yoke git pre-commit", "git", REASON_TOOL_SHAPED),
    _p("yoke git post-commit", "git", REASON_TOOL_SHAPED),
    # Browser-QA orchestration is client-local (Playwright daemon,
    # screenshots on this machine's disk) — tool-shaped like the git hook
    # bodies; its DB legs are the wrapped qa.* ids above. The screenshot
    # token is the manual-fallback capture; the module form was checkout-only
    # from ambient python3.
    _p("yoke qa browser run", "qa.browser", REASON_TOOL_SHAPED),
    _p("yoke qa browser setup", "qa.browser", REASON_TOOL_SHAPED),
    _p("yoke qa browser screenshot", "qa.browser", REASON_TOOL_SHAPED),
    _p("yoke qa browser status", "qa.browser", REASON_TOOL_SHAPED),
    *tuple(_p(f"yoke core {verb}", "core.local", REASON_TOOL_SHAPED) for verb in ("build", "start", "status", "logs", "stop", "upgrade")),
    # Local mode: universe birth + embedded Postgres lifecycle run on the
    # caller's own machine (there is no control plane to dispatch through
    # until they have run) — tool-shaped like the other machine-setup flows.
    _p("yoke init", "local_universe", REASON_TOOL_SHAPED),
    *tuple(
        _p(f"yoke local-postgres {verb}", "local_universe.postgres",
           REASON_TOOL_SHAPED)
        for verb in ("start", "status", "stop")
    ),
    # Universe export dumps the machine-held database via pg_dump — a
    # client-local file operation gated on DSN possession, not a
    # dispatcher function id.
    _p("yoke universe export", "local_universe.export", REASON_TOOL_SHAPED),
    _p("yoke universe validate", "local_universe.validate", REASON_TOOL_SHAPED),
    _p("yoke source-authority quiesce", "source_authority.quiesce", REASON_TOOL_SHAPED),
    _p("yoke source-authority export", "source_authority.export", REASON_TOOL_SHAPED),
    # Self-host mode: bundle materialization writes compose files on the
    # caller's machine; connect verifies a server then writes machine
    # config + a token secret file. Both run before/without an active
    # connection, so there is no control plane to dispatch through —
    # tool-shaped like the other machine-setup flows.
    _p("yoke self-host init", "self_host", REASON_TOOL_SHAPED),
    _p("yoke self-host import", "self_host.import", REASON_TOOL_SHAPED),
    _p("yoke connect", "self_host.connect", REASON_TOOL_SHAPED),
    # Machine-local token-gated UI server (reads dispatch in-process).
    _p("yoke ui", "local_universe.ui", REASON_TOOL_SHAPED),
    _p("yoke check file-line", "checks.file_line", REASON_TOOL_SHAPED),
    _p("yoke board art variant create", "board.art", REASON_TOOL_SHAPED),
    _p("yoke resync", "resync", REASON_TOOL_SHAPED), _p("yoke schema converge", "schema", REASON_TOOL_SHAPED),
    *INSTALLER_LOCAL_PERMANENT_ROWS,
    # Tool-shaped — agent executes via harness; no function id.
    _p("python3 -m yoke_core.tools.module_source_path",
       "tools.module_source_path", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_pytest",
       "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_doctor",
       "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_merge",
       "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_deploy",
       "tools.watch", REASON_TOOL_SHAPED),
    # The remaining agent-facing watcher surfaces.
    # watch_advance / watch_lifecycle / watch_session_offer are
    # taught in conduct's dispatch-context-artifacts.md; watch_tail is the
    # Monitor command every --print-streaming-pair emits; watch_inventory
    # is the pre-authoring drift check taught in the Claude session rules.
    _p("python3 -m yoke_core.tools.watch_advance",
       "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_lifecycle",
       "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_session_offer",
       "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_tail",
       "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_inventory",
       "tools.watch", REASON_TOOL_SHAPED),
    *STRATEGY_EVENT_PERMANENT_ROWS,
    _p("python3 -m yoke_core.cli.db_router query",
       "raw.sql", REASON_OPERATOR_BREAK_GLASS),
    # Deployment pipeline — long-running command-shaped boundary (like the
    # merge/done-transition watchers): usher drives it; not a quick typed
    # function call. Flow admin (delete) is operator break-glass.
    _p("python3 -m yoke_core.domain.deploy_pipeline",
       "deployment_runs", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.domain.flow delete",
       "deployment_flows", REASON_OPERATOR_BREAK_GLASS),
    # Environment DB bootstrap — env-lifecycle command-shaped boundary
    # (deploy-executor outer form + DSN-pinned inner form a self-hoster
    # runs directly against an explicit YOKE_PG_DSN authority).
    _p("python3 -m yoke_core.domain.deploy_environment_bootstrap",
       "deployment_runs", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.domain.environment_bootstrap",
       "deployment_runs", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.verify_env_auth_boundary",
       "deployment_runs", REASON_TOOL_SHAPED),
    # Ephemeral preview deploy/teardown — same long-running deploy
    # command-shaped boundary as deploy_pipeline; flow stage executor +
    # operator CLI. Flow stage admin (update-stages) is operator
    # break-glass like flow delete.
    _p("python3 -m yoke_core.domain.deploy_ephemeral",
       "deployment_runs", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.domain.flow update-stages",
       "deployment_flows", REASON_OPERATOR_BREAK_GLASS),
    # Unified worktree creation provisions git worktrees on disk and runs
    # lane preflight; no safe dispatcher/function-call wrapper exists yet.
    _p("python3 -m yoke_core.domain.worktree create",
       "worktree", REASON_TOOL_SHAPED),
    _p("yoke merge audit", "merge", REASON_TOOL_SHAPED),
    _p("yoke usher reconcile-github", "usher", REASON_TOOL_SHAPED),
)

PENDING_ROWS: Tuple[_Row, ...] = (
    # qa family: fully converted. Reads/creation/gate-summary registered
    # by the dispatcher-backed qa CRUD slice (wrapped rows above). Two prior
    # pending rows reconciled without minting ids: `qa run-add` is
    # already wrapped as qa.run.add by the browser-QA family, and
    # `qa run-satisfy-screenshot-evidence` duplicate-collapsed into the
    # registered qa.screenshot_evidence.satisfy (same guard, SQL, and
    # insert as qa_evidence_bridge.cmd_satisfy_screenshot_evidence).
    # events read family: `events list` was dispositioned as covered by
    # the registered `events.query.run` (its request model carries every
    # list filter incl. --current-episode); tail/count/anomalies are
    # wrapped above. The db_router forms remain operator-debug fallbacks.
    # deployment_runs / deployment_flows: fully dispatcher-backed.
)
__all__ = [
    "_Row", "WRAPPED", "PERMANENT", "PENDING", "REASON_WRAPPED_BY_YOKE_CLI",
    "REASON_OPERATOR_BREAK_GLASS", "REASON_TOOL_SHAPED",
    "REASON_NO_HANDLER_REGISTERED", "WRAPPED_ROWS", "PERMANENT_ROWS", "PENDING_ROWS",
]
