"""The retired surface names ``HC-obsoleted-terms`` hunts for.

Data, not behaviour: the patterns, their human-readable labels, and the
per-pattern path allowlists. The scan that consumes them lives in
``check_obsoleted_terms``. Splitting the catalogue out keeps a table that
grows with every retirement from crowding the scanner it feeds.

Every retirement of a surface adds one entry to
:data:`OBSOLETED_TERM_PATTERNS` in the *same commit* that removes the
surface, plus a short label in :data:`OBSOLETED_TERM_LABELS`.
"""

from __future__ import annotations

from yoke_core.engines.doctor_hc_obsoleted_terms_allowlists import (
    CODEX_HOOKS_AUDIT_PATHS,
    YOKE_DB_AUDIT_PATHS,
)
from yoke_core.engines import doctor_hc_obsoleted_terms_browser as _browser_terms
from yoke_core.engines import (
    doctor_hc_obsoleted_terms_coordination as _coordination_terms,
)
from yoke_core.engines import doctor_hc_obsoleted_terms_db_authority as _db_terms
from yoke_core.engines import doctor_hc_obsoleted_terms_packs as _pack_terms
from yoke_core.engines import (
    doctor_hc_obsoleted_terms_session_control as _session_terms,
)
from yoke_core.engines import (
    doctor_hc_obsoleted_terms_item_dependency as _item_dep_terms,
)
from yoke_core.engines import doctor_hc_obsoleted_terms_plan_limits as _plan_limit_terms
from yoke_project_checks import _obsoleted_terms_inbox as _inbox_terms
from yoke_project_checks._obsoleted_terms_subject_paths import (
    MIGRATION_RETIREMENT_SUBJECT_PATHS,
    QA_PACKET_TEACHING_PATHS,
    QA_RUNNER_RENAME_SUBJECT_PATHS,
)

_RETIRED_PARENT_EPIC_SYMBOL_PATTERN = r"items" + r"\." + "epic"
_RETIRED_PARENT_EPIC_CLI_PATTERN = r"items\s+(get|update|set)\s+\S+\s+" + "epic" + r"\b"
# SQL form: catches ``items WHERE epic = …`` and the screenshot-shape
# ``items WHERE epic_id IN (…)``. Tight enough that ``epic_tasks WHERE epic_id``
# (no leading ``items`` token) and ``id={epic-id-…}`` placeholders (``epic``
# preceded by ``{`` or ``-``, not by a SQL delimiter) do not trigger. Requiring
# a predicate operator after the field also prevents the scanner from crossing
# a closed Python query string into a later ``(int(epic_id),)`` argument.
_RETIRED_PARENT_EPIC_SQL_PATTERN = (
    r"\bitems\b"
    + r"[^\n]*"
    + r"\bWHERE\b"
    + r"[^\n]*"
    + r"[\s,(]"
    + "epic"
    + r"(_id)?\s*"
    + r"(?:=|<>|!=|<=|>=|<|>|\bIN\b|\bIS\b|\bLIKE\b)"
)
# SQL select-list form: catches ``SELECT epic_id FROM items ...``. Keep this
# separate from the WHERE-clause form so each stale shape has a focused label.
_RETIRED_PARENT_EPIC_SQL_SELECT_PATTERN = (
    r"\bSELECT\b"
    + r"[^\n]*"
    + r"[\s,(]"
    + "epic"
    + r"(_id)?[\s,)]"
    + r"[^\n]*"
    + r"\bFROM\s+items\b"
)
# Prose form: catches ``the `epic` field on a backlog item`` and bare
# ``epic field on the item``. Optional backticks bracket the field token.
_RETIRED_EPIC_FIELD_PROSE_PATTERN = (
    r"`?" + "epic" + r"`?\s*field\s+on\s+(?:a|the)\s+(?:backlog\s+)?item\b"
)
# Backlog ontology prose: ``child issue`` / ``child issues``. The retired ontology
# implied items had a parent-child relationship in ``items``; today they are flat
# rows. GitHub-side parent issues are sync metadata for ``epic_tasks``, not items.
_RETIRED_CHILD_ISSUE_PATTERN = r"\b" + "child" + r"\s+" + "issue" + r"s?\b"
# Backlog ontology prose: the ``type=issue with an epic parent`` shape, which
# explicitly named the retired item-level parent link. Tolerant of backtick
# wrapping around either token.
_RETIRED_TYPE_ISSUE_EPIC_PARENT_PATTERN = (
    r"type" + r"\s*=\s*" + "issue" + r"\b[^\n]+" + "epic" + r"[^\n]{0,5}" + "parent"
)

# Coalesced patterns for the hook-runner cutover. Each grouped pattern covers
# a family of retired sibling module slugs whose individual identification is
# preserved by the matched line text rendered in the doctor report; the family
# label below names the shared retirement.
_RETIRED_CODEX_HOOKS_SIBLINGS_PATTERN = (
    r"runtime\.harness\.codex\.codex_hooks_"
    r"(tool_events|session_start|stop|prompt_submit|service_bridge)\b"
)
_RETIRED_SESSION_HOOKS_PER_EVENT_PATTERN = (
    r"\bsession_hooks_(denial|telemetry|side_effects|payload|identity|"
    r"orientation_checks|orientation_content|session_start|session_end|"
    r"user_prompt_submit|plan_render|target_resolution|service_client)\b"
)
# Routed-ownership rename: retired telemetry + field names. Three
# explicit patterns so each obsoleted token is named individually in the
# label registry per AGENTS.md "Obsoleted terms must not appear" rule.
_RETIRED_RECENT_OWNER_EXCLUSIONS_PATTERN = r"\brecent_owner_exclusions\b"
_RETIRED_EXCLUDED_RECENT_OWNER_COUNT_PATTERN = r"\bexcluded_recent_owner_count\b"
_RETIRED_EXCLUDED_RECENT_OWNER_PATTERN = r"\bexcluded_recent_owner\b"

# Workspace-based project resolvers are retired in favor of the canonical
# session project-scope resolver. Both names register as obsoleted so future
# references trip the HC.
_RETIRED_WORKSPACE_RESOLVER_CLI_PATTERN = r"\bresolve_project_from_workspace_cli\b"
_RETIRED_WORKSPACE_RESOLVER_HTTP_PATTERN = r"\b_resolve_project_from_workspace\b"
_RETIRED_PRODUCT_NAME_PATTERN = r"\b[Ss]unday\b"
# Retired product domain token (URL compounds like ``api.<domain>.com`` defeat
# the bare-name boundary) and retired item-id prefix. The ``[s]`` class and the
# ``\d+`` escape keep each declaration from matching itself, like ``[Ss]unday``.
_RETIRED_PRODUCT_DOMAIN_PATTERN = r"(?i)\b[s]undaydo\b"
_RETIRED_ITEM_PREFIX_PATTERN = r"\bSUN-\d+\b"
_RETIRED_QA_AUTO_MODULE_PATTERN = r"\byoke_core\.domain\.qa_requirements_auto\b"
_RETIRED_QA_AUTO_FUNCTION_PATTERN = r"\bqa\.requirement\.auto_create_for_item\b"
_RETIRED_QA_AUTO_CLI_PATTERN = r"\byoke\s+qa\s+requirement\s+auto-create-for-item\b"
_RETIRED_WORK_ITEM_SYNONYM_PATTERN = r"\b" + "tick" + r"ets?\b"

# QA runner rename: retired executor_* columns become runner_*.
_RETIRED_QA_EXECUTOR_ID_PATTERN = r"\b" + "executor" + r"_id\b"
_RETIRED_QA_EXECUTOR_TYPE_PATTERN = r"\b" + "executor" + r"_type\b"
_RETIRED_QA_EXECUTOR_GLOSS_PATTERN = r"\b" + "executor" + r"_gloss\b"
_RETIRED_QA_EXECUTOR_CLI_PATTERN = r"--" + "executor" + r"-type\b"
_RETIRED_HOST_CONTROL_EXECUTOR_PATTERN = r"\bhost_control_" + "executor" + r"\b"
_RETIRED_EPHEMERAL_MIGRATION_MODULE_PATTERN = (
    r"yoke_core\.domain\.(?:migration_auto_retire|migration_install_topology"
    r"|migration_retire_record|migration_apply_manifest|migration_source_checkout"
    r"|migration_source_digest|migration_manifest_validation|portable_migration"
    r"|deploy_pipeline_migration|flow_cross_reference)\b"
)
_RETIRED_LIVE_APPLY_CLI_PATTERN = r"migration_apply\s+live-apply\b"
_RETIRED_MODULE_PATH_OVERRIDE_PATTERN = r"--module-path-override\b"
_RETIRED_MIGRATION_APPLY_STAGE_PATTERN = r'"kind"\s*:\s*"migration_apply"'
_RETIRED_APPLIED_EVERYWHERE_PATTERN = r"applied\-everywhere evidence"
_RETIRED_LANE_OVERRIDE_IGNORED_EVENT_PATTERN = "SessionOffer" + r"LaneOverrideIgnored\b"

#: The file-driven deployment-flow declaration: a project repository no longer
#: defines its flows, so the reconcile command, its function id, and the
#: declaration modules are all gone. Flows are created and retired by command.
#: The ``.yoke/deployment-flows.json`` files still sitting in project
#: repositories are deliberately NOT matched. They were left in place and are
#: the owning project's to keep, retire, or keep reading from its own tests —
#: so their keys (``retire_if_present`` among them) are data in a file Yoke no
#: longer owns rather than live Yoke surface names.
_RETIRED_FLOW_RECONCILE_CLI_PATTERN = r"deployment-flows\s+" + "reconcile" + r"-project"
_RETIRED_FLOW_RECONCILE_FUNCTION_PATTERN = (
    r"deployment_flows\." + "reconcile" + r"_project\b"
)
_RETIRED_FLOW_DECLARATION_MODULE_PATTERN = (
    r"deployment_flow_declaration" + r"(_schema)?\b"
)
_RETIRED_FLOW_DECLARATION_CONTRACT_PATTERN = (
    r"yoke_contracts\.project_contract\.deployment_flows\b"
)

OBSOLETED_TERM_PATTERNS: tuple[str, ...] = (
    *_coordination_terms.COORDINATION_LEASE_RETIREMENT_PATTERNS,
    _RETIRED_PARENT_EPIC_SYMBOL_PATTERN,
    # CLI-argument form of the same retired parent-epic item field. The shape is
    # deliberately tight — ``items (get|update|set)`` must be followed by actual
    # whitespace, then a single non-whitespace ID token, then another whitespace,
    # then the bare field name at a word boundary. This stops prose that mentions
    # ``items update`` and the field name in separate clauses on one line.
    _RETIRED_PARENT_EPIC_CLI_PATTERN,
    _RETIRED_PARENT_EPIC_SQL_PATTERN,
    _RETIRED_PARENT_EPIC_SQL_SELECT_PATTERN,
    _RETIRED_EPIC_FIELD_PROSE_PATTERN,
    _RETIRED_CHILD_ISSUE_PATTERN,
    _RETIRED_TYPE_ISSUE_EPIC_PARENT_PATTERN,
    r"yoke_core\.domain\.doctor",
    r"yoke-db\.sh",
    r"runtime\.harness\.session_hooks\b",
    r"runtime\.harness\.codex\.codex_hooks\b",
    _RETIRED_CODEX_HOOKS_SIBLINGS_PATTERN,
    r"runtime\.harness\.session_hooks_register\b",
    r"runtime\.harness\.hook_helpers_executor\b",
    _RETIRED_SESSION_HOOKS_PER_EVENT_PATTERN,
    _RETIRED_RECENT_OWNER_EXCLUSIONS_PATTERN,
    _RETIRED_EXCLUDED_RECENT_OWNER_COUNT_PATTERN,
    _RETIRED_EXCLUDED_RECENT_OWNER_PATTERN,
    _RETIRED_WORKSPACE_RESOLVER_CLI_PATTERN,
    _RETIRED_WORKSPACE_RESOLVER_HTTP_PATTERN,
    _RETIRED_PRODUCT_NAME_PATTERN,
    _RETIRED_PRODUCT_DOMAIN_PATTERN,
    _RETIRED_ITEM_PREFIX_PATTERN,
    _RETIRED_QA_AUTO_MODULE_PATTERN,
    _RETIRED_QA_AUTO_FUNCTION_PATTERN,
    _RETIRED_QA_AUTO_CLI_PATTERN,
    _RETIRED_WORK_ITEM_SYNONYM_PATTERN,
    _RETIRED_QA_EXECUTOR_ID_PATTERN,
    _RETIRED_QA_EXECUTOR_TYPE_PATTERN,
    _RETIRED_QA_EXECUTOR_GLOSS_PATTERN,
    _RETIRED_QA_EXECUTOR_CLI_PATTERN,
    _RETIRED_HOST_CONTROL_EXECUTOR_PATTERN,
    *_session_terms.SESSION_CONTROL_RETIREMENT_PATTERNS,
    *_item_dep_terms.ITEM_DEPENDENCY_RETIREMENT_PATTERNS,
    *_plan_limit_terms.PLAN_LIMIT_RETIREMENT_PATTERNS,
    # Ephemeral-migration compensation is gone; boot converge applies history.
    _RETIRED_EPHEMERAL_MIGRATION_MODULE_PATTERN,
    _RETIRED_LIVE_APPLY_CLI_PATTERN,
    _RETIRED_MODULE_PATH_OVERRIDE_PATTERN,
    _RETIRED_MIGRATION_APPLY_STAGE_PATTERN,
    _RETIRED_APPLIED_EVERYWHERE_PATTERN,
    _RETIRED_LANE_OVERRIDE_IGNORED_EVENT_PATTERN,
    _RETIRED_FLOW_RECONCILE_CLI_PATTERN,
    _RETIRED_FLOW_RECONCILE_FUNCTION_PATTERN,
    _RETIRED_FLOW_DECLARATION_MODULE_PATTERN,
    _RETIRED_FLOW_DECLARATION_CONTRACT_PATTERN,
    *_browser_terms.BROWSER_RETIREMENT_PATTERNS,
    *_pack_terms.PACK_RETIREMENT_PATTERNS,
    *_db_terms.DB_AUTHORITY_RETIREMENT_PATTERNS,
    *_inbox_terms.INBOX_RETIREMENT_PATTERNS,
)

OBSOLETED_TERM_LABELS: dict[str, str] = {
    **_coordination_terms.COORDINATION_LEASE_RETIREMENT_LABELS,
    _RETIRED_FLOW_RECONCILE_CLI_PATTERN: (
        "retired file-driven deployment-flow reconcile CLI "
        "(use `yoke deployment-flows create` / `set-status`)"
    ),
    _RETIRED_FLOW_RECONCILE_FUNCTION_PATTERN: (
        "retired file-driven deployment-flow reconcile function id "
        "(use `deployment_flows.create`)"
    ),
    _RETIRED_FLOW_DECLARATION_MODULE_PATTERN: (
        "retired deployment-flow declaration module"
    ),
    _RETIRED_FLOW_DECLARATION_CONTRACT_PATTERN: (
        "retired deployment-flow declaration contract module "
        "(tier vocabulary moved to `yoke_contracts.deployment_flow_target_tier`)"
    ),
    _RETIRED_EPHEMERAL_MIGRATION_MODULE_PATTERN: "retired ephemeral-migration module",
    _RETIRED_LIVE_APPLY_CLI_PATTERN: "retired live-apply CLI (boot converge applies)",
    _RETIRED_MODULE_PATH_OVERRIDE_PATTERN: "retired cross-worktree module override",
    _RETIRED_MIGRATION_APPLY_STAGE_PATTERN: "retired migration_apply deployment stage",
    _RETIRED_APPLIED_EVERYWHERE_PATTERN: "retired applied-everywhere deletion rule",
    _RETIRED_LANE_OVERRIDE_IGNORED_EVENT_PATTERN: (
        "SessionOfferLaneOverrideIgnored (retired — caller lane now overrides "
        "the session-row default and emits SessionOfferLaneOverrideApplied)"
    ),
    _RETIRED_PARENT_EPIC_SYMBOL_PATTERN: "retired parent-epic item field (symbol form)",
    _RETIRED_PARENT_EPIC_CLI_PATTERN: "retired parent-epic item field (CLI form)",
    _RETIRED_PARENT_EPIC_SQL_PATTERN: "retired parent-epic item field (SQL form)",
    _RETIRED_PARENT_EPIC_SQL_SELECT_PATTERN: "retired parent-epic item field (SQL select-list form)",
    _RETIRED_EPIC_FIELD_PROSE_PATTERN: "retired parent-epic item field (prose form)",
    _RETIRED_CHILD_ISSUE_PATTERN: "retired backlog ontology phrase (child issue)",
    _RETIRED_TYPE_ISSUE_EPIC_PARENT_PATTERN: "retired backlog ontology phrase (type=issue with epic parent)",
    r"yoke_core\.domain\.doctor": "yoke_core.domain.doctor (nonexistent module path)",
    r"yoke-db\.sh": "yoke-db.sh (retired shell wrapper)",
    r"runtime\.harness\.session_hooks\b": "runtime.harness.session_hooks (retired — collapsed into runtime.harness.hook_runner)",
    r"runtime\.harness\.codex\.codex_hooks\b": "runtime.harness.codex.codex_hooks (retired — collapsed into runtime.harness.hook_runner)",
    _RETIRED_CODEX_HOOKS_SIBLINGS_PATTERN: "runtime.harness.codex.codex_hooks_<event> sibling (retired — collapsed into runtime.harness.hook_runner)",
    r"runtime\.harness\.session_hooks_register\b": "runtime.harness.session_hooks_register (retired — renamed to runtime.harness.hook_runner_register)",
    r"runtime\.harness\.hook_helpers_executor\b": "runtime.harness.hook_helpers_executor (retired — renamed to runtime.harness.hook_helpers_identity)",
    _RETIRED_SESSION_HOOKS_PER_EVENT_PATTERN: "session_hooks_<event> (retired per-event sibling)",
    _RETIRED_RECENT_OWNER_EXCLUSIONS_PATTERN: "recent_owner_exclusions (retired — renamed to routed_ownership_exclusions)",
    _RETIRED_EXCLUDED_RECENT_OWNER_COUNT_PATTERN: "excluded_recent_owner_count (retired telemetry key — renamed to excluded_routed_ownership_count)",
    _RETIRED_EXCLUDED_RECENT_OWNER_PATTERN: "excluded_recent_owner (retired telemetry prefix — renamed to excluded_routed_ownership)",
    _RETIRED_WORKSPACE_RESOLVER_CLI_PATTERN: "resolve_project_from_workspace_cli (retired workspace resolver — replaced by resolve_session_project_scope)",
    _RETIRED_WORKSPACE_RESOLVER_HTTP_PATTERN: "_resolve_project_from_workspace (retired workspace resolver — replaced by resolve_session_project_scope)",
    _RETIRED_PRODUCT_NAME_PATTERN: "Sunday/sunday (retired product name — replaced by Yoke/yoke)",
    _RETIRED_PRODUCT_DOMAIN_PATTERN: "sundaydo (retired product domain token — replaced by upyoke.com)",
    _RETIRED_ITEM_PREFIX_PATTERN: "SUN-<digits> (retired item prefix — replaced by YOK-<digits>)",
    _RETIRED_QA_AUTO_MODULE_PATTERN: "retired QA auto-requirement module",
    _RETIRED_QA_AUTO_FUNCTION_PATTERN: "retired QA auto-requirement function",
    _RETIRED_QA_AUTO_CLI_PATTERN: "retired QA auto-requirement command",
    _RETIRED_WORK_ITEM_SYNONYM_PATTERN: "retired work-item synonym",
    _RETIRED_QA_EXECUTOR_ID_PATTERN: (
        "qa_methods/qa_requirements executor_id (retired QA column — renamed to runner_id)"
    ),
    _RETIRED_QA_EXECUTOR_TYPE_PATTERN: (
        "qa_runs executor_type (retired QA column — renamed to performed_by)"
    ),
    _RETIRED_QA_EXECUTOR_GLOSS_PATTERN: (
        "qa_methods executor_gloss (retired QA column — renamed to runner_gloss)"
    ),
    _RETIRED_QA_EXECUTOR_CLI_PATTERN: (
        "--executor-type (retired QA run flag — renamed to --performed-by)"
    ),
    _RETIRED_HOST_CONTROL_EXECUTOR_PATTERN: (
        "host_control_executor (retired module — renamed to host_control_runner)"
    ),
    **_session_terms.SESSION_CONTROL_RETIREMENT_LABELS,
    **_item_dep_terms.ITEM_DEPENDENCY_RETIREMENT_LABELS,
    **_plan_limit_terms.PLAN_LIMIT_RETIREMENT_LABELS,
    **_browser_terms.BROWSER_RETIREMENT_LABELS,
    **_pack_terms.PACK_RETIREMENT_LABELS,
    **_db_terms.DB_AUTHORITY_RETIREMENT_LABELS,
    **_inbox_terms.INBOX_RETIREMENT_LABELS,
}

# Scan scope

# Per-pattern path allow-list. Each entry is a repo-relative path string;
# matching is prefix-based so a single entry covers a file family. Audit-
# infrastructure prefixes live in :mod:`doctor_hc_obsoleted_terms_allowlists`
# alongside the broader per-file exemption, and this project's own subject
# path families in :mod:`_obsoleted_terms_subject_paths`; the dict below
# composes those tuples per pattern.
_PER_PATTERN_PATH_ALLOWLIST: dict[str, tuple[str, ...]] = {
    **_coordination_terms.COORDINATION_LEASE_RETIREMENT_ALLOWLIST,
    **_db_terms.DB_AUTHORITY_RETIREMENT_ALLOWLIST,
    _RETIRED_QA_EXECUTOR_ID_PATTERN: QA_RUNNER_RENAME_SUBJECT_PATHS
    + QA_PACKET_TEACHING_PATHS,
    _RETIRED_QA_EXECUTOR_TYPE_PATTERN: QA_RUNNER_RENAME_SUBJECT_PATHS
    + QA_PACKET_TEACHING_PATHS,
    _RETIRED_QA_EXECUTOR_GLOSS_PATTERN: QA_RUNNER_RENAME_SUBJECT_PATHS,
    _RETIRED_QA_EXECUTOR_CLI_PATTERN: (
        # The lifecycle DB-command lint reproduces the retired
        # ``qa-db.sh run-add`` invocation verbatim so it can still
        # recognise that legacy shape in tracked content; the flag
        # spelling is part of the shape it detects.
        "packages/yoke-core/src/yoke_core/domain/lint_db_rules_lifecycle.py",
    ),
    _RETIRED_HOST_CONTROL_EXECUTOR_PATTERN: QA_RUNNER_RENAME_SUBJECT_PATHS,
    **_session_terms.SESSION_CONTROL_RETIREMENT_ALLOWLIST,
    **_item_dep_terms.ITEM_DEPENDENCY_RETIREMENT_ALLOWLIST,
    _RETIRED_MIGRATION_APPLY_STAGE_PATTERN: MIGRATION_RETIREMENT_SUBJECT_PATHS,
    _RETIRED_EPHEMERAL_MIGRATION_MODULE_PATTERN: MIGRATION_RETIREMENT_SUBJECT_PATHS,
    _RETIRED_LANE_OVERRIDE_IGNORED_EVENT_PATTERN: MIGRATION_RETIREMENT_SUBJECT_PATHS
    + ("packages/yoke-core/src/yoke_core/domain/populate_registry_data_lifecycle.py",),
    **{
        pattern: MIGRATION_RETIREMENT_SUBJECT_PATHS
        for pattern in _inbox_terms.INBOX_RETIREMENT_MIGRATION_SUBJECT_PATTERNS
    },
    r"yoke-db\.sh": YOKE_DB_AUDIT_PATHS,
    r"runtime\.harness\.codex\.codex_hooks\b": CODEX_HOOKS_AUDIT_PATHS,
}
