"""Registered function-id routes for the ``yoke`` operations CLI."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters
from yoke_cli.commands.adapters.items_merge_provenance import (
    items_merge_provenance_operator_correct,
)
from yoke_cli.commands.adapters.lifecycle_repair import lifecycle_repair_status
from yoke_cli.commands.adapters.claims_path_change import claims_path_amend
from yoke_cli.commands.adapters.config import env_list
from yoke_cli.commands.registry_token_normalization import expanded_hyphen_routes
from yoke_cli.commands.registry_deployment import DEPLOYMENT_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_ephemeral_env import EPHEMERAL_ENV_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_epic_ops import EPIC_OPS_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_github_actions import (
    GITHUB_ACTIONS_SUBCOMMAND_ALIAS_REGISTRY,
    GITHUB_ACTIONS_SUBCOMMAND_REGISTRY,
)
from yoke_cli.commands.registry_github import GITHUB_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_claims import (
    CLAIMS_SUBCOMMAND_ALIAS_REGISTRY,
    CLAIMS_SUBCOMMAND_REGISTRY,
)
from yoke_cli.commands.registry_identity import IDENTITY_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_organizations import ORGANIZATION_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_items_flags import ITEMS_FLAGS_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_projects import PROJECTS_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_qa import QA_SUBCOMMAND_REGISTRY
from yoke_cli.commands import registry_product_surfaces as _product_surfaces
from yoke_cli.commands.registry_db_claim import DB_CLAIM_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_readiness import READINESS_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_shepherd_dependency import (
    SHEPHERD_DEPENDENCY_SUBCOMMAND_REGISTRY,
)
from yoke_cli.commands.registry_sessions import SESSIONS_SUBCOMMAND_REGISTRY
from yoke_cli.commands import registry_session_control as _session_control
from yoke_cli.commands.registry_strategy_event import STRATEGY_EVENT_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_workflows import WORKFLOW_SUBCOMMAND_REGISTRY

AdapterFn = Callable[[List[str]], int]
# (cli_tokens) -> (function_id, adapter_fn)
SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("items", "create"): ("items.create", _adapters.items_create),
    ("items", "get"): ("items.get.run", _adapters.items_get),
    ("items", "list"): ("items.list.run", _adapters.items_list),
    ("items", "search"): ("items.search.run", _adapters.items_search),
    ("items", "github-sync"): ("items.github_sync", _adapters.items_github_sync),
    ("items", "progress-log", "append"): (
        "items.progress_log.append",
        _adapters.items_progress_log_append,
    ),
    ("items", "structured-field", "replace"): (
        "items.structured_field.replace",
        _adapters.items_structured_field_replace,
    ),
    ("items", "scalar", "update"): (
        "items.scalar.update",
        _adapters.items_scalar_update,
    ),
    **ITEMS_FLAGS_SUBCOMMAND_REGISTRY,
    ("items", "merge-provenance", "operator-correct"): (
        "items.merge_provenance.operator_correct",
        items_merge_provenance_operator_correct,
    ),
    ("items", "section", "upsert"): (
        "items.section.upsert",
        _adapters.items_section_upsert,
    ),
    ("items", "section", "get"): ("items.section.get", _adapters.items_section_get),
    ("items", "section", "delete"): (
        "items.section.delete",
        _adapters.items_section_delete,
    ),
    ("items", "structured-field", "append-addendum"): (
        "items.structured_field.append_addendum",
        _adapters.items_structured_field_append_addendum,
    ),
    ("items", "structured-field", "section-upsert"): (
        "items.structured_field.section_upsert",
        _adapters.items_structured_field_section_upsert,
    ),
    ("items", "structured-field", "section-append"): (
        "items.structured_field.section_append",
        _adapters.items_structured_field_section_append,
    ),
    ("claims", "work", "acquire"): (
        "claims.work.acquire",
        _adapters.claims_work_acquire,
    ),
    ("claims", "work", "release"): (
        "claims.work.release",
        _adapters.claims_work_release,
    ),
    ("claims", "path", "register"): (
        "claims.path.register",
        _adapters.claims_path_register,
    ),
    ("claims", "path", "widen"): ("claims.path.widen", _adapters.claims_path_widen),
    ("claims", "path", "amend"): ("claims.path.amend", claims_path_amend),
    ("claims", "path", "list"): ("claims.path.list", _adapters.claims_path_list),
    ("claims", "path", "get"): ("claims.path.get", _adapters.claims_path_get),
    ("claims", "path", "coordination-decision-build"): (
        "claims.path.coordination_decision_build",
        _adapters.claims_path_coordination_decision_build,
    ),
    ("claims", "work", "holder-get"): (
        "claims.work.holder_get",
        _adapters.claims_work_holder_get,
    ),
    ("claims", "work", "holder-list"): (
        "claims.work.holder_list",
        _adapters.claims_work_holder_list,
    ),
    ("path-claims", "conflicts", "list"): (
        "path_claims.conflicts.list",
        _adapters.path_claims_conflicts_list,
    ),
    ("db", "read"): ("db.read.run", _adapters.db_read),
    ("charge", "schedule"): ("charge.schedule", _adapters.charge_schedule),
    ("frontier", "list"): ("frontier.list", _adapters.frontier_list),
    ("agents", "render"): ("agents.render.run", _adapters.agents_render),
    ("agents", "render", "check"): (
        "agents.render.check",
        _adapters.agents_render_check,
    ),
    ("packets", "render"): ("packets.render.run", _adapters.packets_render),
    ("packets", "check"): ("packets.check.run", _adapters.packets_check),
    ("board", "rebuild"): ("board.rebuild.run", _adapters.board_rebuild),
    ("board", "data", "get"): ("board.data.get", _adapters.board_data_get),
    ("lint", "config", "show"): ("lint.config.show", _adapters.lint_config_show),
    ("hook", "evaluate"): ("hook.evaluate.run", _adapters.hook_evaluate),
    **QA_SUBCOMMAND_REGISTRY,
    ("doctor", "run"): ("doctor.run.run", _adapters.doctor_run),
    ("doctor", "last-run", "get"): (
        "doctor.last_run.get",
        _adapters.doctor_last_run_get,
    ),
    ("events", "query"): ("events.query.run", _adapters.events_query),
    ("events", "tail"): ("events.tail.run", _adapters.events_tail),
    ("events", "count"): ("events.count.run", _adapters.events_count),
    ("events", "anomalies"): ("events.anomalies.run", _adapters.events_anomalies),
    ("lifecycle", "transition"): (
        "lifecycle.transition.execute",
        _adapters.lifecycle_transition,
    ),
    ("lifecycle", "repair-status"): (
        "lifecycle.repair_status.execute",
        lifecycle_repair_status,
    ),
    ("lifecycle", "skip", "record-recoverable-substrate"): (
        "lifecycle.skip.record_recoverable_substrate",
        _adapters.lifecycle_skip_record_recoverable_substrate,
    ),
    ("ouroboros", "field-note", "append"): (
        "ouroboros.field_note.append",
        _adapters.ouroboros_field_note_append,
    ),
    ("ouroboros", "field-note", "list"): (
        "ouroboros.field_note.list",
        _adapters.ouroboros_field_note_list,
    ),
    ("ouroboros", "field-note", "get"): (
        "ouroboros.field_note.get",
        _adapters.ouroboros_field_note_get,
    ),
    ("ouroboros", "entry", "list"): (
        "ouroboros.entry.list",
        _adapters.ouroboros_entry_list,
    ),
    ("ouroboros", "entry", "get"): (
        "ouroboros.entry.get",
        _adapters.ouroboros_entry_get,
    ),
    ("strategy", "doc", "list"): ("strategy.doc.list", _adapters.strategy_doc_list),
    ("strategy", "doc", "get"): ("strategy.doc.get", _adapters.strategy_doc_get),
    ("strategy", "doc", "create"): (
        "strategy.doc.create",
        _adapters.strategy_doc_create,
    ),
    ("strategy", "doc", "replace"): (
        "strategy.doc.replace",
        _adapters.strategy_doc_replace,
    ),
    ("strategy", "doc", "archive"): (
        "strategy.doc.archive",
        _adapters.strategy_doc_archive,
    ),
    ("strategy", "doc", "unarchive"): (
        "strategy.doc.unarchive",
        _adapters.strategy_doc_unarchive,
    ),
    ("strategy", "render"): ("strategy.render.run", _adapters.strategy_render),
    ("strategy", "ingest"): ("strategy.ingest.run", _adapters.strategy_ingest),
    ("strategy", "seed-defaults"): (
        "strategy.seed_defaults.run",
        _adapters.strategy_seed_defaults,
    ),
    ("scratch", "dispatch-inputs"): (
        "scratch.dispatch_inputs",
        _adapters.scratch_dispatch_inputs,
    ),
    ("config", "example"): ("config.example.run", _adapters.config_example),
    ("config", "stamp-project-env"): (
        "config.stamp_project_env.run",
        _adapters.config_stamp_project_env,
    ),
    ("config", "status"): ("config.status.run", _adapters.status),
    ("status",): ("status.run", _adapters.status),
    ("onboard", "checklist", "init"): (
        "onboard.checklist.init",
        _adapters.onboard_checklist_init,
    ),
    ("onboard", "checklist"): (
        "onboard.checklist.run",
        _adapters.onboard_checklist_cmd,
    ),
    ("env", "use"): ("env.use.run", _adapters.env_use),
    ("env", "list"): ("env.list.run", env_list),
    ("connection", "set"): ("connection.set.run", _adapters.connection_set),
    ("connection", "remove"): ("connection.remove.run", _adapters.connection_remove),
    ("auth", "set"): ("auth.set.run", _adapters.auth_set),
    ("packs", "list"): ("packs.list", _adapters.packs_list),
    ("packs", "get"): ("packs.get.run", _adapters.packs_get),
    ("packs", "relink"): ("packs.relink.run", _adapters.packs_relink),
    ("packs", "update"): ("packs.update.run", _adapters.packs_update),
}

SUBCOMMAND_REGISTRY.update(SHEPHERD_DEPENDENCY_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(SESSIONS_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(_session_control.SESSION_CONTROL_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(EPIC_OPS_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(DEPLOYMENT_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(EPHEMERAL_ENV_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(DB_CLAIM_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(READINESS_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(STRATEGY_EVENT_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(IDENTITY_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(ORGANIZATION_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(CLAIMS_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(GITHUB_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(GITHUB_ACTIONS_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(PROJECTS_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(WORKFLOW_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(_product_surfaces.PRODUCT_SURFACE_SUBCOMMAND_REGISTRY)


# Aliases keep the primary registry 1:1 with function-id grammar.
SUBCOMMAND_ALIAS_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    **_product_surfaces.PRODUCT_SURFACE_SUBCOMMAND_ALIAS_REGISTRY,
    ("projects", "capability", "secret", "set"): (
        "projects.capability_secret.set",
        _adapters.projects_capability_secret_set,
    ),
    ("claims", "work", "current"): (
        "claims.work.holder_get",
        _adapters.claims_work_current,
    ),
    ("claims", "work", "status"): (
        "claims.work.holder_get",
        _adapters.claims_work_current,
    ),
}
SUBCOMMAND_ALIAS_REGISTRY.update(GITHUB_ACTIONS_SUBCOMMAND_ALIAS_REGISTRY)
SUBCOMMAND_ALIAS_REGISTRY.update(CLAIMS_SUBCOMMAND_ALIAS_REGISTRY)
SUBCOMMAND_ALIAS_REGISTRY.update(
    _session_control.SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY
)
SPACE_EXPANDED_ROUTE_REGISTRY = expanded_hyphen_routes(
    SUBCOMMAND_REGISTRY,
    SUBCOMMAND_ALIAS_REGISTRY,
)
_TOKEN_LENGTHS: Tuple[int, ...] = tuple(
    range(
        max(
            max(map(len, SUBCOMMAND_REGISTRY), default=1),
            max(
                max(map(len, SUBCOMMAND_ALIAS_REGISTRY), default=1),
                max(map(len, SPACE_EXPANDED_ROUTE_REGISTRY), default=1),
            ),
        ),
        0,
        -1,
    )
)


def resolve(argv_head: List[str]) -> Tuple[Tuple[str, ...], str, AdapterFn, List[str]]:
    """Resolve the longest registered route prefix from ``argv_head``."""
    for length in _TOKEN_LENGTHS:
        if len(argv_head) < length:
            continue
        candidate = tuple(argv_head[:length])
        if candidate in SUBCOMMAND_REGISTRY:
            function_id, adapter = SUBCOMMAND_REGISTRY[candidate]
            return candidate, function_id, adapter, argv_head[length:]
        if candidate in SUBCOMMAND_ALIAS_REGISTRY:
            function_id, adapter = SUBCOMMAND_ALIAS_REGISTRY[candidate]
            return candidate, function_id, adapter, argv_head[length:]
        if candidate in SPACE_EXPANDED_ROUTE_REGISTRY:
            function_id, adapter = SPACE_EXPANDED_ROUTE_REGISTRY[candidate]
            return candidate, function_id, adapter, argv_head[length:]
    raise KeyError(
        "unknown subcommand: {!r}; see `yoke --help` for the canonical list.".format(
            " ".join(argv_head[: max(_TOKEN_LENGTHS)])
        )
    )


# Grammar-rule helpers (used by tests and --help text)


def function_id_to_cli(function_id: str) -> Tuple[str, ...]:
    """Drop synthetic terminals and translate dots/underscores to CLI tokens."""
    parts = function_id.split(".")
    if parts and parts[-1] in ("run", "execute"):
        parts = parts[:-1]
    return tuple(p.replace("_", "-") for p in parts)


def cli_to_function_id_stem(tokens: Tuple[str, ...]) -> str:
    """Translate CLI tokens to a function-id stem without its terminal."""
    return ".".join(t.replace("-", "_") for t in tokens)


__all__ = [
    "SUBCOMMAND_REGISTRY",
    "SUBCOMMAND_ALIAS_REGISTRY",
    "SPACE_EXPANDED_ROUTE_REGISTRY",
    "AdapterFn",
    "resolve",
    "function_id_to_cli",
    "cli_to_function_id_stem",
]
