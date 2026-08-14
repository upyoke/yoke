"""Permanent operator/break-glass rows for the operation tracker.

Split from :mod:`yoke_cli.operation_inventory_data` so that module stays
inside the authored-file line budget. These rows describe surfaces that
stay command-shaped by design rather than awaiting a CLI adapter.
"""

from __future__ import annotations

from typing import Tuple
from yoke_cli.operation_inventory_model import (
    REASON_OPERATOR_BREAK_GLASS,
    REASON_TOOL_SHAPED,
    _p,
    _Row,
)
from yoke_cli.operation_inventory_installer_local import (
    PERMANENT_ROWS as INSTALLER_LOCAL_PERMANENT_ROWS,
)
from yoke_cli.operation_inventory_product_surfaces import (
    PERMANENT_ROWS as PRODUCT_SURFACE_PERMANENT_ROWS,
)
from yoke_cli.operation_inventory_strategy_event import (
    PERMANENT_ROWS as STRATEGY_EVENT_PERMANENT_ROWS,
)


PERMANENT_ROWS: Tuple[_Row, ...] = (
    *PRODUCT_SURFACE_PERMANENT_ROWS,
    # Coordination-lease family — operator break-glass.
    _p(
        "python3 -m yoke_core.api.service_client coordination-lease-acquire",
        "claims.coordination_lease",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    _p(
        "python3 -m yoke_core.api.service_client coordination-lease-heartbeat",
        "claims.coordination_lease",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    _p(
        "python3 -m yoke_core.api.service_client coordination-lease-list",
        "claims.coordination_lease",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    _p(
        "python3 -m yoke_core.api.service_client coordination-lease-release",
        "claims.coordination_lease",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    _p(
        "yoke coordination-lease release",
        "coordination_lease",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    # claims.path operator-only paths.
    _p(
        "python3 -m yoke_core.api.service_client path-claim-override",
        "claims.path",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    _p(
        "python3 -m yoke_core.api.service_client claim-release",
        "claims.work",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    _p("yoke migration rehearse", "migration.apply", REASON_TOOL_SHAPED),
    _p(
        "python3 -m yoke_core.domain.path_integrity verify",
        "path_integrity",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    _p(
        "python3 -m yoke_core.domain.install_bundle_tree_sync sync",
        "install_bundle.sync",
        REASON_TOOL_SHAPED,
    ),
    _p(
        "python3 -m yoke_core.cli.db_router path-claims activate",
        "claims.path",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    _p(
        "python3 -m yoke_core.cli.db_router path-claims amend",
        "claims.path",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    _p(
        "python3 -m yoke_core.cli.db_router path-claims release",
        "claims.path",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    # Tool-shaped local git/filesystem operations — deliberately NOT
    # dispatcher function ids; routed as CLI tokens by yoke_cli.main.
    _p("yoke git pre-commit", "git", REASON_TOOL_SHAPED),
    _p("yoke git post-commit", "git", REASON_TOOL_SHAPED),
    _p("yoke sessions init", "sessions", REASON_TOOL_SHAPED),
    # Registered CLI commands that intentionally execute on the caller's
    # machine instead of crossing the function-call dispatcher.
    _p("yoke agents render", "agents.render", REASON_TOOL_SHAPED),
    _p("yoke agents render check", "agents.render", REASON_TOOL_SHAPED),
    _p("yoke lint config show", "lint.config", REASON_TOOL_SHAPED),
    _p("yoke packets render", "packets", REASON_TOOL_SHAPED),
    _p("yoke packets check", "packets", REASON_TOOL_SHAPED),
    _p("yoke scratch dispatch-inputs", "scratch", REASON_TOOL_SHAPED),
    _p("yoke config example", "config", REASON_TOOL_SHAPED),
    _p("yoke config stamp-project-env", "config", REASON_TOOL_SHAPED),
    _p("yoke config status", "config", REASON_TOOL_SHAPED),
    _p("yoke status", "status", REASON_TOOL_SHAPED),
    _p("yoke env use", "env", REASON_TOOL_SHAPED),
    _p("yoke env list", "env", REASON_TOOL_SHAPED),
    _p("yoke connection set", "connection", REASON_TOOL_SHAPED),
    _p("yoke connection remove", "connection", REASON_TOOL_SHAPED),
    _p("yoke auth set", "auth", REASON_TOOL_SHAPED),
    _p("yoke project register", "project", REASON_TOOL_SHAPED),
    _p("yoke project install", "project", REASON_TOOL_SHAPED),
    _p("yoke project refresh", "project", REASON_TOOL_SHAPED),
    _p("yoke project uninstall", "project", REASON_TOOL_SHAPED),
    _p("yoke packs get", "packs", REASON_TOOL_SHAPED),
    _p("yoke packs relink", "packs", REASON_TOOL_SHAPED),
    _p("yoke packs update", "packs", REASON_TOOL_SHAPED),
    # QA case execution and Browser substrate utilities are client-local.
    # The case runner executes one materialized method requirement.
    _p("yoke qa case run", "qa.case", REASON_TOOL_SHAPED),
    _p("yoke qa plan run", "qa.plan", REASON_TOOL_SHAPED),
    _p("yoke qa plan review-submit", "qa.plan", REASON_TOOL_SHAPED),
    _p("yoke qa plan abort", "qa.plan", REASON_TOOL_SHAPED),
    _p("yoke qa browser setup", "qa.browser", REASON_TOOL_SHAPED),
    _p("yoke qa browser screenshot", "qa.browser", REASON_TOOL_SHAPED),
    _p("yoke qa browser status", "qa.browser", REASON_TOOL_SHAPED),
    *tuple(
        _p(f"yoke core {verb}", "core.local", REASON_TOOL_SHAPED)
        for verb in ("build", "start", "status", "logs", "stop", "upgrade")
    ),
    # Local mode: universe birth + embedded Postgres lifecycle run on the
    # caller's own machine (there is no control plane to dispatch through
    # until they have run) — tool-shaped like the other machine-setup flows.
    _p("yoke init", "local_universe", REASON_TOOL_SHAPED),
    *tuple(
        _p(f"yoke local-postgres {verb}", "local_universe.postgres", REASON_TOOL_SHAPED)
        for verb in ("start", "status", "stop")
    ),
    # Universe export dumps the machine-held database via pg_dump — a
    # client-local file operation gated on DSN possession, not a
    # dispatcher function id.
    _p("yoke universe export", "universe.export", REASON_TOOL_SHAPED),
    _p("yoke universe import", "universe.import", REASON_TOOL_SHAPED),
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
    _p("yoke merge item", "merge.item", REASON_TOOL_SHAPED),
    _p("yoke local demo seed", "local.demo", REASON_TOOL_SHAPED),
    _p("yoke path check", "path", REASON_TOOL_SHAPED),
    _p("yoke path fix", "path", REASON_TOOL_SHAPED),
    _p("yoke path verify", "path", REASON_TOOL_SHAPED),
    _p("yoke vps start", "vps", REASON_TOOL_SHAPED),
    _p("yoke vps status", "vps", REASON_TOOL_SHAPED),
    _p("yoke vps stop", "vps", REASON_TOOL_SHAPED),
    _p("yoke resync", "resync", REASON_TOOL_SHAPED),
    _p("yoke schema converge", "schema", REASON_TOOL_SHAPED),
    *INSTALLER_LOCAL_PERMANENT_ROWS,
    # Tool-shaped — agent executes via harness; no function id.
    _p(
        "python3 -m yoke_core.tools.module_source_path",
        "tools.module_source_path",
        REASON_TOOL_SHAPED,
    ),
    # The three agent-facing watcher adapters live in TOOL_CLI_ROWS: they
    # are first-class yoke commands but still execute local subprocesses.
    # The tail follower remains a permanent local helper because it is the
    # capture-consumer primitive emitted by the streaming pair.
    _p("yoke watch tail", "tools.watch", REASON_TOOL_SHAPED),
    # The same four wrappers as module forms. Retained as the
    # operator-debug fallback, so recipes that predate the adapters keep
    # working and the argparse-bypass classifier below still resolves them.
    _p("python3 -m yoke_core.tools.watch_pytest", "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_doctor", "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_merge", "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_tail", "tools.watch", REASON_TOOL_SHAPED),
    # The remaining agent-facing watcher surfaces, module-form only.
    # watch_advance / watch_lifecycle / watch_session_offer are
    # taught in conduct's dispatch-context-artifacts.md; watch_inventory
    # is the pre-authoring drift check taught in the Claude session rules.
    _p("python3 -m yoke_core.tools.watch_advance", "tools.watch", REASON_TOOL_SHAPED),
    _p("python3 -m yoke_core.tools.watch_lifecycle", "tools.watch", REASON_TOOL_SHAPED),
    _p(
        "python3 -m yoke_core.tools.watch_session_offer",
        "tools.watch",
        REASON_TOOL_SHAPED,
    ),
    _p("python3 -m yoke_core.tools.watch_inventory", "tools.watch", REASON_TOOL_SHAPED),
    _p(
        "python3 -m yoke_core.tools.step_runners",
        "tools.step_runners",
        REASON_TOOL_SHAPED,
    ),
    *STRATEGY_EVENT_PERMANENT_ROWS,
    _p(
        "python3 -m yoke_core.cli.db_router query",
        "raw.sql",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    # Deployment pipeline — long-running command-shaped boundary (like the
    # merge/done-transition watchers): usher drives it; not a quick typed
    # function call. Flow admin (delete) is operator break-glass.
    _p(
        "python3 -m yoke_core.domain.deploy_pipeline",
        "deployment_runs",
        REASON_TOOL_SHAPED,
    ),
    _p("yoke deployment-runs execute", "deployment_runs", REASON_TOOL_SHAPED),
    _p(
        "python3 -m yoke_core.domain.flow delete",
        "deployment_flows",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    # Environment DB bootstrap — env-lifecycle command-shaped boundary
    # (deploy-step_runner outer form + DSN-pinned inner form a self-hoster
    # runs directly against an explicit YOKE_PG_DSN authority).
    _p(
        "python3 -m yoke_core.domain.deploy_environment_bootstrap",
        "deployment_runs",
        REASON_TOOL_SHAPED,
    ),
    _p(
        "python3 -m yoke_core.domain.environment_bootstrap",
        "deployment_runs",
        REASON_TOOL_SHAPED,
    ),
    _p(
        "python3 -m yoke_core.tools.verify_env_auth_boundary",
        "deployment_runs",
        REASON_TOOL_SHAPED,
    ),
    # Ephemeral preview deploy/teardown — same long-running deploy
    # command-shaped boundary as deploy_pipeline; flow stage step_runner +
    # operator CLI. Flow stage admin (update-stages) is operator
    # break-glass like flow delete.
    _p(
        "python3 -m yoke_core.domain.deploy_ephemeral",
        "deployment_runs",
        REASON_TOOL_SHAPED,
    ),
    _p(
        "python3 -m yoke_core.domain.flow update-stages",
        "deployment_flows",
        REASON_OPERATOR_BREAK_GLASS,
    ),
    # Unified worktree creation provisions git worktrees on disk and runs
    # lane preflight; no safe dispatcher/function-call wrapper exists yet.
    _p("python3 -m yoke_core.domain.worktree create", "worktree", REASON_TOOL_SHAPED),
    _p("yoke merge audit", "merge", REASON_TOOL_SHAPED),
    _p("yoke usher reconcile-github", "usher", REASON_TOOL_SHAPED),
)


__all__ = ["PERMANENT_ROWS"]
