"""Keep newly authored migrations and table schemas below live domain policy.

This source contract deliberately does not read the database architecture snapshot.
Applied migration entries through 0106 retain their historical imports.
"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
DOMAIN = ROOT / "packages/yoke-core/src/yoke_core/domain"
# Explicit module membership: a name ending in _schema or _contract is no proof
# that its implementation belongs below live domain invariants.
CORE_LAYERS = {
    "schema_storage": """
        audience_schema auth_schema decision_request_contract decision_request_schema
        deployment_run_pipe_format deployment_runs_schema deployment_stage_receipt_schema
        external_identity_schema frontend_events_schema gate_satisfaction_schema
        github_app_schema harness_machine_schema health_runs_schema inbox_post_schema
        item_landings_schema item_refs_schema item_worktree_schema
        machine_authorization_schema machine_registry_schema machine_verification_schema
        merge_lock_schema merge_queue_landing_record_schema org_schema
        project_onboarding_schema projects_github_sync_mode_schema projects_restart_schema
        qa_catalog_schema qa_deployment_requirement_identity_schema
        qa_deployment_scope_schema qa_method_definitions qa_plan_execution_schema
        qa_plan_review_schema qa_schema qa_standalone_schema qa_test_machine_wait_schema
        release_start_schema_lock runs schema_actor_message_recipients schema_common
        schema_converge_statements schema_creation schema_deployment_run_lock
        schema_init_apply schema_organization schema_qa_plan_requirement_identity
        schema_qa_settlement_followups schema_session_control_convergence
        schema_teammate_invite_codes session_ci_wait_schema session_control_schema
        session_launch_surface_domain session_message_recipient_schema
        session_scheduled_wake_schema sql_boolean_contract sql_json
        stored_instant_columns strategize_carry_schema strategy_docs_header
        strategy_docs_schema strategy_execution_schema ui_preferences_schema
        workflow_execution_instructions_schema workflow_schema
    """.split(),
    "persistence_queries": "db_backend db_helpers".split(),
    "payload_validators": "migration_ledger_contract json_helper".split(),
    "migrations": """
        migration_content_adoption migration_content_schema
        migration_content_schema_ownership migration_content_transition_guard
        migration_fleet_ownership
    """.split(),
}
ALLOWED_CORE = {
    f"yoke_core.domain.{module}"
    for modules in CORE_LAYERS.values()
    for module in modules
}

# Operator-approved existing edges, restricted to their current source owners.
# Retire each exception when its dependency moves out of the schema module.
EXISTING_EDGES = {
    ("external_identity_schema.py", "yoke_core.domain.actor_visitor_links"),
    ("release_start_schema.py", "yoke_core.domain.environment_bootstrap"),
}


def imported_modules(source: str, package: str):
    """Include lazy imports and normalize relative and package-from spellings."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            if module in {"yoke_core", "yoke_core.domain"}:
                for alias in node.names:
                    yield node.lineno, f"{module}.{alias.name}"
            else:
                yield node.lineno, module


def violations(source: str, package: str, filename: str = ""):

    for line, module in imported_modules(source, package):
        if (
            module.split(".")[0] in sys.stdlib_module_names
            or module == "psycopg"
            or module.startswith("psycopg.")
            or module == "yoke_contracts"
            or module.startswith("yoke_contracts.")
            or module in ALLOWED_CORE
            or (filename, module) in EXISTING_EDGES
        ):
            continue
        yield (
            f"line {line}: forbidden import {module}; allowed layers: "
            f"stdlib, psycopg, yoke_contracts, {', '.join(CORE_LAYERS)} "
            "(explicit module allow-list). Move live policy to orchestration "
            "and pass the required data into the migration/schema."
        )


def guarded_paths(domain: Path = DOMAIN):
    yield from sorted(domain.glob("*_schema.py"))
    for path in sorted((domain / "migrations").glob("[0-9]*_*.py")):
        if int(path.name.split("_", 1)[0]) > 106:
            yield path


@pytest.mark.parametrize("path", list(guarded_paths()), ids=lambda p: p.name)
def test_migrations_and_schema_import_only_allowed_layers(path):
    package = "yoke_core.domain" + (
        ".migrations" if path.parent.name == "migrations" else ""
    )
    errors = list(violations(path.read_text(), package, path.name))
    assert not errors, f"{path.relative_to(ROOT)}:\n" + "\n".join(errors)


@pytest.mark.parametrize(
    "source",
    [
        "import yoke_core.domain.backlog as policy",
        "from yoke_core.domain import backlog as policy",
        "from yoke_core import domain",
        "from ..backlog import update_status",
        "def apply(conn):\n    from yoke_core.domain.backlog import update_status",
        "from yoke_cli import main",
    ],
)
def test_bad_import_fixture_names_import_and_allowed_layers(source):
    errors = list(violations(source, "yoke_core.domain.migrations"))
    assert len(errors) == 1
    assert "forbidden import yoke_" in errors[0]
    assert "allowed layers:" in errors[0]
    assert "schema_storage" in errors[0]


def test_lower_layer_import_spellings_are_allowed():
    source = """
import json
import psycopg
from yoke_contracts import refusal_recovery
from yoke_core.domain import db_backend
from ..schema_common import _get_columns
from yoke_core.domain.migration_ledger_contract import LedgerContract
"""
    assert not list(violations(source, "yoke_core.domain.migrations"))


@pytest.mark.parametrize("filename,module", sorted(EXISTING_EDGES))
def test_existing_edge_exception_is_restricted_to_its_owner(filename, module):
    source = f"import {module}"
    assert not list(violations(source, "yoke_core.domain", filename))
    assert list(violations(source, "yoke_core.domain", "new_schema.py"))
    assert list(violations(source, "yoke_core.domain.migrations", "0107_new.py"))
    assert list(
        violations("import yoke_core.domain.backlog", "yoke_core.domain", filename)
    )


def test_guard_discovers_new_migrations_and_schema_modules(tmp_path):
    (tmp_path / "migrations").mkdir()
    names = ["0106_existing.py", "0107_new.py", "0108_new.py", "_helper.py"]
    for name in names:
        (tmp_path / "migrations" / name).touch()
    (tmp_path / "new_schema.py").touch()
    (tmp_path / "policy.py").touch()
    assert {p.name for p in guarded_paths(tmp_path)} == {
        "new_schema.py",
        "0107_new.py",
        "0108_new.py",
    }
