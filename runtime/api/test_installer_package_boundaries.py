"""Guard engine import boundaries for the client packages.

The engine ships beside the clients, but the active connection decides whether
it runs: HTTPS relays to the server, non-prod local Postgres dispatches in
process, and prod-flagged Postgres stays operator-only. Client packages cannot
take static authority over engine/runtime/database modules before that transport
decision. Dynamic imports remain limited to the lanes named below.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOTS = (
    ROOT / "packages" / "yoke-cli" / "src" / "yoke_cli",
    ROOT / "packages" / "yoke-contracts" / "src" / "yoke_contracts",
    ROOT / "packages" / "yoke-harness" / "src" / "yoke_harness",
)
ENGINE_IMPORT_BOUNDARY_ROOTS = frozenset(
    {"psycopg", "psycopg2", "runtime", "yoke_core"}
)

ALLOWED_DYNAMIC_AUTHORITY_IMPORTS = {
    (
        "packages/yoke-cli/src/yoke_cli/commands/_helpers.py",
        "yoke_core.domain.handlers.__init_register__",
    ): (
        "local_universe_dispatch",
        "handler registration for local-universe in-process dispatch",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/board.py",
        "yoke_core.cli.board_rebuild_timing_events",
    ): ("client_local_diagnostics", "board rebuild timing event adapter"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/board.py",
        "yoke_core.domain.events_writes",
    ): ("client_local_diagnostics", "board rebuild event writer fallback"),
    (
        "packages/yoke-cli/src/yoke_cli/board/source_dev_extras.py",
        "yoke_core.domain.lock_helper",
    ): ("client_local_diagnostics", "board rebuild file lock (source-dev only)"),
    (
        "packages/yoke-cli/src/yoke_cli/board/source_dev_extras.py",
        "yoke_core.domain.workspace_authority",
    ): (
        "client_local_diagnostics",
        "board rebuild seed-source check (source-dev only)",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/board/source_dev_extras.py",
        "yoke_core.domain.schema",
    ): (
        "client_local_diagnostics",
        "board rebuild seed-source module (source-dev only)",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/board/source_dev_extras.py",
        "yoke_core.domain.connected_env_readiness",
    ): (
        "client_local_diagnostics",
        "board rebuild connected-env classifier (source-dev only)",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/board/source_dev_extras.py",
        "yoke_core.domain.rebuild_board_outcome",
    ): (
        "client_local_diagnostics",
        "board rebuild outcome event emit (source-dev only)",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/github_actions.py",
        "yoke_core.domain.github_actions_run_monitoring",
    ): ("source_dev_admin", "local GitHub Actions monitor helper"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/github_actions_wait.py",
        "yoke_core.domain.github_actions_run_monitoring",
    ): ("source_dev_admin", "local GitHub Actions wait helper"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/misc.py",
        "yoke_core.domain.handlers.ouroboros_field_note",
    ): ("source_dev_admin", "local field-note adapter until HTTPS-only"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/misc.py",
        "yoke_core.domain.project_scratch_dir",
    ): ("source_dev_admin", "local scratch resolver helper"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/projects_secret.py",
        "yoke_core.domain.capability_machine_secrets",
    ): ("source_dev_admin", "local aws-admin capability secret file writer"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/resync.py",
        "yoke_core.engines.resync",
    ): ("source_dev_admin", "sanctioned resync source-dev/admin command"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/schema_converge.py",
        "yoke_core.api.server_entrypoint",
    ): (
        "source_dev_admin",
        "sanctioned additive schema convergence source-dev/admin command",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/schema_converge.py",
        "yoke_core.domain.cloud_db_secret_dsn",
    ): (
        "source_dev_admin",
        "schema convergence authority-conflict guard",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/merge_audit.py",
        "yoke_core.engines.merge_audit",
    ): ("source_dev_admin", "sanctioned merge audit source-dev/admin command"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/usher_reconcile.py",
        "yoke_core.engines.usher_reconcile_github",
    ): ("source_dev_admin", "sanctioned usher recovery source-dev/admin command"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/source_authority.py",
        "yoke_core.domain.source_authority_cutover",
    ): (
        "source_dev_admin",
        "attended source-authority credential cutoff and export boundary",
    ),
    ("packages/yoke-cli/src/yoke_cli/commands/universe_validate.py",
     "yoke_core.domain.universe_archive_validation"):
        ("client_local_validation", "validate a local archive before upload"),
    (
        "packages/yoke-cli/src/yoke_cli/config/dev_setup.py",
        "yoke_core.tools.pg_testcluster",
    ): ("source_dev_admin", "explicit disposable Postgres setup branch"),
    (
        "packages/yoke-cli/src/yoke_cli/config/db_admin_setup.py",
        "yoke_core.domain.yoke_cloud_db_authority",
    ): (
        "source_dev_admin",
        "explicit managed cloud database credential setup branch",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/config/local_universe_setup.py",
        "yoke_core.domain.local_universe",
    ): (
        "local_engine_activation",
        "local mode runs the embedded engine on this machine by design",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/config/local_universe_setup.py",
        "yoke_core.domain.universe_export",
    ): (
        "local_engine_activation",
        "universe export dumps the machine-held database via the engine",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/local_universe.py",
        "yoke_core.domain.db_backend",
    ): (
        "local_engine_activation",
        "local demo seeding uses the engine DSN env contract",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/config/existing_project_lookup.py",
        "yoke_core.domain.db_backend",
    ): (
        "local_engine_activation",
        "local project-reuse lookup reads the engine DSN env contract to verify local project metadata",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/local_universe.py",
        "yoke_core.domain.local_demo_seed",
    ): (
        "local_engine_activation",
        "local demo seeding writes demo rows through the embedded engine",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/universe_ui.py",
        "yoke_core.api.server_entrypoint",
    ): (
        "local_engine_activation",
        "the local-universe UI boot converges the embedded engine schema "
        "before serving",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/universe_ui.py",
        "yoke_core.ui.server",
    ): (
        "local_engine_activation",
        "the local-universe UI server runs the engine on this machine by design",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/config/db_admin_setup.py",
        "yoke_core.domain.deploy_core_container",
    ): ("source_dev_admin", "explicit db-admin setup cloud binding resolver"),
    (
        "packages/yoke-cli/src/yoke_cli/config/db_admin_setup.py",
        "yoke_core.domain.deploy_environment_settings",
    ): ("source_dev_admin", "explicit db-admin setup environment resolver"),
    (
        "packages/yoke-cli/src/yoke_cli/config/db_admin_setup.py",
        "yoke_core.domain.deploy_remote",
    ): ("source_dev_admin", "explicit db-admin setup AWS command helper"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/dev.py",
        "yoke_core.domain.db_helpers",
    ): ("source_dev_admin", "explicit path-snapshot prewarm DB helper"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/dev.py",
        "yoke_core.domain.path_snapshots",
    ): ("source_dev_admin", "explicit path-snapshot prewarm builder"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/dev.py",
        "yoke_core.domain.path_snapshots_integration_warm",
    ): ("source_dev_admin", "explicit integration-target prewarm builder"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/aws.py",
        "yoke_core.domain.deploy_remote",
    ): ("source_dev_admin", "explicit aws-admin capability subprocess helper"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/runner_fleet.py",
        "yoke_core.tools.runner_fleet_exec",
    ): (
        "source_dev_admin",
        "explicit runner-fleet credential-scoped child-process helper",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/project_install/source_dev.py",
        "yoke_core.domain.project_install_source_link",
    ): ("source_dev_admin", "explicit source-link setup branch only"),
    (
        "packages/yoke-cli/src/yoke_cli/project_install/transport.py",
        "yoke_core.domain.db_backend",
    ): (
        "local_engine_activation",
        "local-postgres project install uses the engine DSN env contract",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/project_install/transport.py",
        "yoke_core.domain.db_helpers",
    ): (
        "local_engine_activation",
        "local-postgres project install reads the local universe database",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/project_install/transport.py",
        "yoke_core.domain.install_bundle",
    ): (
        "local_engine_activation",
        "local-postgres project install renders bundles through the engine",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/transport/dispatcher.py",
        "yoke_core.domain.yoke_function_dispatch",
    ): (
        "local_universe_dispatch",
        "in-process dispatch branch for non-https connections",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/transport/local_github_dispatch.py",
        "yoke_core.domain.project_github_auth",
    ): (
        "local_universe_dispatch",
        "project-scoped GitHub App token dispatch for a local universe",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/transport/local_github_dispatch.py",
        "yoke_core.domain.github_actions_local_authority",
    ): (
        "local_universe_dispatch",
        "explicit attended GitHub Actions bootstrap dispatcher",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/hooks.py",
        "runtime.harness.hook_runner.local_universe_lifecycle",
    ): (
        "local_universe_dispatch",
        "drive the in-process session lifecycle for a bound local universe",
    ),
}


def _root_name(module: str) -> str:
    return module.split(".", 1)[0]


def _iter_python_files() -> list[Path]:
    paths: list[Path] = []
    for package_root in PACKAGE_ROOTS:
        paths.extend(sorted(package_root.rglob("*.py")))
    return paths


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if not isinstance(func, ast.Attribute):
        return ""
    parts = [func.attr]
    cur = func.value
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _literal_module_arg(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def test_cli_and_contract_packages_do_not_take_direct_core_imports():
    violations: list[str] = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _root_name(alias.name) in ENGINE_IMPORT_BOUNDARY_ROOTS:
                        violations.append(f"{rel}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _root_name(module) in ENGINE_IMPORT_BOUNDARY_ROOTS:
                    violations.append(f"{rel}:{node.lineno}: from {module} import ...")
    assert violations == []


def test_dynamic_authority_imports_are_classified_and_bounded():
    observed: set[tuple[str, str]] = set()
    violations: list[str] = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) not in {
                "__import__",
                "import_module",
                "importlib.import_module",
            }:
                continue
            module = _literal_module_arg(node)
            if module is None or _root_name(module) not in ENGINE_IMPORT_BOUNDARY_ROOTS:
                continue
            key = (rel, module)
            observed.add(key)
            if key not in ALLOWED_DYNAMIC_AUTHORITY_IMPORTS:
                violations.append(f"{rel}:{node.lineno}: {module}")
    stale_allowlist = sorted(
        f"{rel}: {module}"
        for rel, module in set(ALLOWED_DYNAMIC_AUTHORITY_IMPORTS) - observed
    )
    assert violations == []
    assert stale_allowlist == []
    for classification, rationale in ALLOWED_DYNAMIC_AUTHORITY_IMPORTS.values():
        assert classification
        assert rationale
