"""Hand-curated ``yoke <subcommand>`` registry.

Entries map CLI token tuples to ``(function_id, adapter)`` pairs. The
strict grammar is: dots become spaces, underscores become hyphens, and
terminal ``.run`` / ``.execute`` segments drop.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters
from yoke_cli.commands.registry_deployment import DEPLOYMENT_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_ephemeral_env import EPHEMERAL_ENV_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_epic_ops import EPIC_OPS_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_github_actions import (
    GITHUB_ACTIONS_SUBCOMMAND_ALIAS_REGISTRY,
    GITHUB_ACTIONS_SUBCOMMAND_REGISTRY,
)
from yoke_cli.commands.registry_identity import IDENTITY_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_projects import PROJECTS_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_project_structure import PROJECT_STRUCTURE_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_readiness import READINESS_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_shepherd_dependency import SHEPHERD_DEPENDENCY_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_strategy_event import STRATEGY_EVENT_SUBCOMMAND_REGISTRY

AdapterFn = Callable[[List[str]], int]
# (cli_tokens) -> (function_id, adapter_fn)
SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("items", "create"): ("items.create", _adapters.items_create),
    ("items", "get"): ("items.get.run", _adapters.items_get),
    ("items", "list"): ("items.list.run", _adapters.items_list),
    ("items", "search"): ("items.search.run", _adapters.items_search),
    ("items", "github-sync"): ("items.github_sync", _adapters.items_github_sync),
    ("items", "progress-log", "append"):
        ("items.progress_log.append", _adapters.items_progress_log_append),
    ("items", "structured-field", "replace"):
        ("items.structured_field.replace", _adapters.items_structured_field_replace),
    ("items", "scalar", "update"):
        ("items.scalar.update", _adapters.items_scalar_update),
    ("items", "section", "upsert"):
        ("items.section.upsert", _adapters.items_section_upsert),
    ("items", "section", "get"):
        ("items.section.get", _adapters.items_section_get),
    ("items", "section", "delete"):
        ("items.section.delete", _adapters.items_section_delete),
    ("items", "structured-field", "append-addendum"):
        ("items.structured_field.append_addendum",
         _adapters.items_structured_field_append_addendum),
    ("items", "structured-field", "section-upsert"):
        ("items.structured_field.section_upsert",
         _adapters.items_structured_field_section_upsert),
    ("items", "structured-field", "section-append"):
        ("items.structured_field.section_append",
         _adapters.items_structured_field_section_append),
    ("claims", "work", "acquire"):
        ("claims.work.acquire", _adapters.claims_work_acquire),
    ("claims", "work", "release"):
        ("claims.work.release", _adapters.claims_work_release),
    ("claims", "path", "register"):
        ("claims.path.register", _adapters.claims_path_register),
    ("claims", "path", "widen"):
        ("claims.path.widen", _adapters.claims_path_widen),
    ("claims", "path", "list"):
        ("claims.path.list", _adapters.claims_path_list),
    ("claims", "path", "get"):
        ("claims.path.get", _adapters.claims_path_get),
    ("claims", "path", "coordination-decision-build"):
        ("claims.path.coordination_decision_build",
         _adapters.claims_path_coordination_decision_build),
    ("claims", "work", "holder-get"):
        ("claims.work.holder_get", _adapters.claims_work_holder_get),
    ("claims", "work", "holder-list"):
        ("claims.work.holder_list", _adapters.claims_work_holder_list),
    ("path-claims", "conflicts", "list"):
        ("path_claims.conflicts.list", _adapters.path_claims_conflicts_list),
    ("db-claim", "amend"):
        ("db_claim.amend", _adapters.db_claim_amend),
    ("db", "read"): ("db.read.run", _adapters.db_read),
    ("sessions", "begin"): ("sessions.begin", _adapters.sessions_begin),
    ("sessions", "init"): ("sessions.init", _adapters.sessions_init),
    ("sessions", "list"): ("sessions.list", _adapters.sessions_list),
    ("sessions", "touch"): ("sessions.touch", _adapters.sessions_touch),
    ("sessions", "checkpoint"):
        ("sessions.checkpoint", _adapters.sessions_checkpoint),
    ("sessions", "checkpoint-read"):
        ("sessions.checkpoint_read", _adapters.sessions_checkpoint_read),
    ("sessions", "offer"): ("sessions.offer", _adapters.sessions_offer),
    ("sessions", "ownership-guard"):
        ("sessions.ownership_guard", _adapters.sessions_ownership_guard),
    ("charge", "schedule"): ("charge.schedule", _adapters.charge_schedule),
    ("frontier", "list"): ("frontier.list", _adapters.frontier_list),
    ("agents", "render"):
        ("agents.render.run", _adapters.agents_render),
    ("agents", "render", "check"):
        ("agents.render.check", _adapters.agents_render_check),
    ("packets", "render"):
        ("packets.render.run", _adapters.packets_render),
    ("packets", "check"):
        ("packets.check.run", _adapters.packets_check),
    ("board", "rebuild"):
        ("board.rebuild.run", _adapters.board_rebuild),
    ("board", "data", "get"):
        ("board.data.get", _adapters.board_data_get),
    ("hook", "evaluate"):
        ("hook.evaluate.run", _adapters.hook_evaluate),
    ("qa", "requirement", "update"):
        ("qa.requirement.update", _adapters.qa_requirement_update),
    ("qa", "requirement", "auto-create-for-item"):
        ("qa.requirement.auto_create_for_item",
         _adapters.qa_requirement_auto_create_for_item),
    ("qa", "requirement", "waive"):
        ("qa.requirement.waive", _adapters.qa_requirement_waive),
    ("qa", "run", "record-verdict"):
        ("qa.run.record_verdict", _adapters.qa_run_record_verdict),
    ("qa", "browser-context", "get"):
        ("qa.browser_context.get", _adapters.qa_browser_context_get),
    ("qa", "run", "add"):
        ("qa.run.add", _adapters.qa_run_add),
    ("qa", "run", "complete"):
        ("qa.run.complete", _adapters.qa_run_complete),
    ("qa", "artifact", "add"):
        ("qa.artifact.add", _adapters.qa_artifact_add),
    ("qa", "artifact", "presign"):
        ("qa.artifact.presign", _adapters.qa_artifact_presign),
    ("qa", "screenshot-evidence", "pending-count"):
        ("qa.screenshot_evidence.pending_count",
         _adapters.qa_screenshot_evidence_pending_count),
    ("qa", "screenshot-evidence", "satisfy"):
        ("qa.screenshot_evidence.satisfy",
         _adapters.qa_screenshot_evidence_satisfy),
    ("qa", "requirement", "list"):
        ("qa.requirement.list", _adapters.qa_requirement_list),
    ("qa", "requirement", "get"):
        ("qa.requirement.get", _adapters.qa_requirement_get),
    ("qa", "requirement", "add"):
        ("qa.requirement.add", _adapters.qa_requirement_add),
    ("qa", "requirement", "add-batch"):
        ("qa.requirement.add_batch", _adapters.qa_requirement_add_batch),
    ("qa", "run", "list"): ("qa.run.list", _adapters.qa_run_list),
    ("qa", "run", "get"): ("qa.run.get", _adapters.qa_run_get),
    ("qa", "gate-summary"): ("qa.gate_summary.run", _adapters.qa_gate_summary),
    ("doctor", "run"): ("doctor.run.run", _adapters.doctor_run),
    ("doctor", "last-run", "get"):
        ("doctor.last_run.get", _adapters.doctor_last_run_get),
    ("organizations", "get"): ("organizations.get", _adapters.organizations_get),
    ("events", "query"): ("events.query.run", _adapters.events_query),
    ("events", "tail"): ("events.tail.run", _adapters.events_tail),
    ("events", "count"): ("events.count.run", _adapters.events_count),
    ("events", "anomalies"): ("events.anomalies.run", _adapters.events_anomalies),
    ("lifecycle", "transition"):
        ("lifecycle.transition.execute", _adapters.lifecycle_transition),
    ("lifecycle", "skip", "record-recoverable-substrate"):
        ("lifecycle.skip.record_recoverable_substrate",
         _adapters.lifecycle_skip_record_recoverable_substrate),
    ("ouroboros", "field-note", "append"):
        ("ouroboros.field_note.append", _adapters.ouroboros_field_note_append),
    ("ouroboros", "field-note", "list"):
        ("ouroboros.field_note.list", _adapters.ouroboros_field_note_list),
    ("ouroboros", "field-note", "get"):
        ("ouroboros.field_note.get", _adapters.ouroboros_field_note_get),
    ("ouroboros", "entry", "list"):
        ("ouroboros.entry.list", _adapters.ouroboros_entry_list),
    ("ouroboros", "entry", "get"):
        ("ouroboros.entry.get", _adapters.ouroboros_entry_get),
    ("strategy", "doc", "list"):
        ("strategy.doc.list", _adapters.strategy_doc_list),
    ("strategy", "doc", "get"):
        ("strategy.doc.get", _adapters.strategy_doc_get),
    ("strategy", "doc", "create"):
        ("strategy.doc.create", _adapters.strategy_doc_create),
    ("strategy", "doc", "replace"):
        ("strategy.doc.replace", _adapters.strategy_doc_replace),
    ("strategy", "doc", "archive"):
        ("strategy.doc.archive", _adapters.strategy_doc_archive),
    ("strategy", "doc", "unarchive"):
        ("strategy.doc.unarchive", _adapters.strategy_doc_unarchive),
    ("strategy", "render"):
        ("strategy.render.run", _adapters.strategy_render),
    ("strategy", "ingest"):
        ("strategy.ingest.run", _adapters.strategy_ingest),
    ("strategy", "seed-defaults"):
        ("strategy.seed_defaults.run", _adapters.strategy_seed_defaults),
    ("github", "pr", "create"):
        ("github.pr.create", _adapters.github_pr_create),
    ("github", "release", "create-next-tag"):
        ("github.release.create_next_tag",
         _adapters.github_release_create_next_tag),
    ("scratch", "dispatch-inputs"):
        ("scratch.dispatch_inputs", _adapters.scratch_dispatch_inputs),
    ("config", "example"):
        ("config.example.run", _adapters.config_example),
    ("config", "stamp-project-env"):
        ("config.stamp_project_env.run", _adapters.config_stamp_project_env),
    ("status",):
        ("status.run", _adapters.status),
    ("onboard", "checklist", "init"):
        ("onboard.checklist.init", _adapters.onboard_checklist_init),
    ("onboard", "checklist"):
        ("onboard.checklist.run", _adapters.onboard_checklist_cmd),
    ("env", "use"):
        ("env.use.run", _adapters.env_use),
    ("connection", "set"):
        ("connection.set.run", _adapters.connection_set),
    ("connection", "remove"):
        ("connection.remove.run", _adapters.connection_remove),
    ("auth", "set"):
        ("auth.set.run", _adapters.auth_set),
    ("packs", "list"):
        ("packs.catalog.list", _adapters.packs_list),
    ("packs", "get"):
        ("packs.get.run", _adapters.packs_get),
    ("packs", "update"):
        ("packs.update.run", _adapters.packs_update),
    ("workflows", "definition", "get"):
        ("workflows.definition.get", _adapters.workflows_definition_get),
}

SUBCOMMAND_REGISTRY.update(PROJECT_STRUCTURE_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(SHEPHERD_DEPENDENCY_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(EPIC_OPS_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(DEPLOYMENT_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(EPHEMERAL_ENV_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(READINESS_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(STRATEGY_EVENT_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(IDENTITY_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(GITHUB_ACTIONS_SUBCOMMAND_REGISTRY)
SUBCOMMAND_REGISTRY.update(PROJECTS_SUBCOMMAND_REGISTRY)


_TOKEN_LENGTHS: Tuple[int, ...] = (4, 3, 2, 1)


# Operator-facing aliases that route to an existing function id with a
# different argparse adapter. Distinct from SUBCOMMAND_REGISTRY because
# the grammar-rule test asserts every primary cli_tokens tuple is the
# mechanical translation of its function_id; aliases live separately so
# the 1:1 invariant on the primary registry stays intact.
SUBCOMMAND_ALIAS_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("projects", "capability", "secret", "set"):
        ("projects.capability_secret.set",
         _adapters.projects_capability_secret_set),
    # "claims work current" is the intuitive current-claim inspection
    # surface — routes to the same claims.work.holder_get function id.
    ("claims", "work", "current"):
        ("claims.work.holder_get", _adapters.claims_work_current),
    # "claims work status --item YOK-N" is the intuitive post-release
    # claim-verification surface — routes to the same claims.work.holder_get
    # function id (reusing the holder-get adapter that already accepts
    # --item plus positional).
    ("claims", "work", "status"):
        ("claims.work.holder_get", _adapters.claims_work_current),
}
SUBCOMMAND_ALIAS_REGISTRY.update(GITHUB_ACTIONS_SUBCOMMAND_ALIAS_REGISTRY)


def resolve(argv_head: List[str]) -> Tuple[
    Tuple[str, ...], str, AdapterFn, List[str]
]:
    """Find the registered subcommand at the head of ``argv_head``.

    Walks the longest token-tuple first. Returns
    ``(cli_tokens, function_id, adapter, remaining_argv)`` on a match.
    Consults both the primary registry and the alias registry; aliases
    return their own cli_tokens (not the primary's) so callers can
    distinguish the entry point used.
    Raises :class:`KeyError` with a teaching message when no registered
    subcommand prefixes the input.
    """
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
    raise KeyError(
        "unknown subcommand: {!r}; see `yoke --help` for the canonical list."
        .format(" ".join(argv_head[: max(_TOKEN_LENGTHS)]))
    )


# Grammar-rule helpers (used by tests and --help text)

def function_id_to_cli(function_id: str) -> Tuple[str, ...]:
    """Translate a function id to CLI tokens per the grammar rule.

    Mechanical: drop terminal ``.run``/``.execute``, replace each ``_``
    inside a segment with ``-``. The transform is one-way (the synthetic
    terminal carries no information, so it cannot be recovered without
    the registry).
    """
    parts = function_id.split(".")
    if parts and parts[-1] in ("run", "execute"):
        parts = parts[:-1]
    return tuple(p.replace("_", "-") for p in parts)


def cli_to_function_id_stem(tokens: Tuple[str, ...]) -> str:
    """Translate CLI tokens back to the function-id stem (without terminal).

    The synthetic terminal ``.run`` / ``.execute`` cannot be inferred
    mechanically; callers that need the full id consult the registry.
    """
    return ".".join(t.replace("-", "_") for t in tokens)

__all__ = ["SUBCOMMAND_REGISTRY", "SUBCOMMAND_ALIAS_REGISTRY", "AdapterFn", "resolve", "function_id_to_cli", "cli_to_function_id_stem"]
