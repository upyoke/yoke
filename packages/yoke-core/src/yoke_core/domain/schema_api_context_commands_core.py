"""``core`` topic wrapper-command recipes for the agent-context packet.

Sibling of :mod:`schema_api_context_commands` (which combines per-topic
lists into the canonical ``WRAPPER_COMMANDS``). Holds the ``core`` topic
entries: structured-field reads/writes, epic task body/metadata, item
dependency CRUD, db-claim amendment, and the raw diagnostic read recipe.

Recipe shape doctrine (current):
    Recipes for function ids covered by the canonical ``yoke`` CLI
    registry (``items.get.run``, ``items.progress_log.append``,
    ``items.structured_field.replace``, ``lifecycle.transition.execute``,
    ``events.query.run``, ``claims.work.*``, ``claims.path.{register,
    widen}``, ``ouroboros.field_note.append``) use the strict
    ``yoke <subcommand>`` grammar (CLI grammar contract).

    Recipes for newly wrapped families (db-claim, sections, additive
    structured-field transforms, dependency reads) use their registered
    ``yoke`` commands. Raw diagnostic SELECTs use ``yoke db read``.
    Remaining source-dev/admin or break-glass tools (``db_router query``,
    ``atlas_render_docs``, and ``backlog-cli`` families) are labelled
    explicitly as operator-debug surfaces inside a Yoke checkout.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


CORE_COMMANDS: list[dict] = [
    {
        "topic": "core",
        "purpose": "Read structured item field(s) — concrete examples",
        "recipe": (
            "yoke items get YOK-N status title type github_issue\n"
            "yoke items get YOK-N spec"
        ),
        "notes": (
            "Multi-field returns one value per line in field order. Valid "
            "fields: architecture_impact, blocked, blocked_reason, body, "
            "browser_qa_metadata, created_at, db_compatibility_attestation, "
            "db_mutation_profile, deploy_log, deploy_stage, deployed_to, "
            "deployment_flow, design_spec, flow, frozen, github_issue, id, "
            "merged_at, priority, project, rework_count, shepherd_caveats, "
            "shepherd_log, source, spec, status, technical_plan, "
            "test_results, title, type, updated_at, worktree, worktree_plan. "
            "For body-section filtering, use "
            "`yoke items get YOK-N body --section \"## File Budget\"`."
        ),
    },
    {
        "topic": "core",
        "purpose": "Inspect a Yoke item's rendered body (GitHub issue surrogate)",
        "recipe": (
            "yoke items get YOK-N body"
        ),
        "notes": (
            "The rendered body is the source of truth for ticket content "
            "and is auto-synced to the GitHub issue via bearer-token REST. "
            "items.github_issue stores '#NNNN' format and is for outbound "
            "linking only — Yoke automation never shells out to ``gh`` "
            "to read or write the issue; the function-call surface and "
            "``project_github_auth.resolve_project_github_auth`` handle "
            "every GitHub mutation through REST/GraphQL."
        ),
    },
    {
        "topic": "core",
        "purpose": "Inspect open work via registered reads + diagnostic SQL",
        "recipe": (
            "# Recent item scan:\n"
            "yoke items list --project all --fields \"id,status,title\" "
            "--limit 20\n"
            "# All active work claims (diagnostic SQL fallback):\n"
            "yoke db read \"SELECT "
            "id, session_id, target_kind, item_id, epic_id, task_num, "
            "claim_type, claimed_at FROM work_claims WHERE released_at IS "
            "NULL\"\n"
            "# Recent events on a ticket:\n"
            "yoke events query --item YOK-N --limit 20"
        ),
        "notes": (
            "Use ``<>`` not ``!=``. Prefer registered readers such as "
            "`yoke items list` and `yoke claims work holder-get` when "
            "they answer the question. Raw diagnostic SELECTs use "
            "`yoke db read`; `db_router query` is the source-dev/"
            "operator-debug break-glass fallback inside a Yoke checkout, "
            "not the agent default. ``work_claims`` has no ``state``, "
            "``reason``, or ``worktree_path`` columns."
        ),
    },
    {
        "topic": "core",
        "purpose": "Read one section of an item's rendered body",
        "recipe": (
            "yoke items get YOK-N body "
            "--section \"## Section Name\""
        ),
        "notes": (
            "Registered body-section filter. Returns just the named "
            "``## Section Name`` block between that heading and the "
            "next ``## ``. Use for large ticket bodies whose full "
            "render exceeds the read budget. Missing section returns "
            "an empty body with a stderr advisory; exit 0."
        ),
    },
    {
        "topic": "core",
        "purpose": "Write structured item field (canonical agent shape)",
        "recipe": (
            "yoke items structured-field replace YOK-N "
            "--field spec --content-file PATH\n"
            "yoke items structured-field replace YOK-N "
            "--field test_results --stdin < PATH"
        ),
        "notes": (
            "Dispatches items.structured_field.replace, runs render-body "
            "and GitHub sync. Use a prewritten PATH for multiline content; "
            "avoid shell read/merge/write choreography."
        ),
    },
    {
        "topic": "core",
        "purpose": "Apply additive structured-field transform",
        "recipe": (
            "# Progress Log append (canonical agent shape):\n"
            "yoke items progress-log append YOK-N "
            "--headline \"verified tests\" --content-file PATH\n"
            "# Other additive transforms:\n"
            "yoke items structured-field append-addendum YOK-N "
            "--field spec --heading \"Implementation Notes\" "
            "--content-file PATH --json\n"
            "yoke items structured-field section-upsert YOK-N "
            "--section \"Acceptance Criteria\" "
            "--content-file PATH --json"
        ),
        "notes": (
            "Progress Log append routes through ``items.progress_log."
            "append`` and is the agent-facing shape through the registered progress-log append surface. "
            "Other additive variants route through registered "
            "``yoke items structured-field ...`` adapters."
        ),
    },
    {
        "topic": "core",
        "purpose": "List item dependencies (both directions)",
        "recipe": (
            "yoke shepherd dependency-list YOK-N"
        ),
        "notes": (
            "Canonical agent shape (function id "
            "``shepherd.dependency_list.run``); works over https. "
            "Typed rows around item_dependencies — use over raw SQL; "
            "guessed columns are not the canonical schema. Operator-"
            "debug fallback: `python3 -m yoke_core.cli.db_router "
            "shepherd dependency-list YOK-N`."
        ),
    },
    {
        "topic": "core",
        "purpose": "Route serial dependency mutations to authoring packets",
        "recipe": (
            "Use the dependency authoring recipes in the claims packet."
        ),
        "notes": (
            "Dependency add/update/remove are authoring-time surfaces; "
            "their registered command adapters land in the claims/path-"
            "claim authoring packet instead of the compact core packet. "
            "They still route through registered function ids "
            "``shepherd.dependency_add/update/remove.run``."
        ),
    },

    {
        "topic": "core",
        "purpose": "Amend DB-mutation claim on an item",
        "recipe": (
            "yoke db-claim amend YOK-N --reason TEXT "
            "(--state none | --payload JSON | --payload-file PATH | --stdin)"
        ),
        "notes": (
            "`--reason TEXT` is always required. Pick exactly one shape: "
            "`--state none` (convenience shortcut for the negative-default "
            "claim), `--payload <JSON>`, `--payload-file PATH`, or `--stdin`."
        ),
    },
    {
        "topic": "core",
        "purpose": "Inspect Atlas: function ids, yoke CLI, contradictions",
        "recipe": (
            "python3 -m yoke_core.tools.atlas_render_docs check\n"
            "yoke ouroboros field-note append --kind new "
            "--evidence 'Missing CLI adapter for <function_id>'"
        ),
        "notes": (
            "The Atlas (`docs/atlas.md`) is the operator-readable view "
            "of every agent-facing surface: function ids registered, "
            "`yoke` CLI subcommands wrapped, permanent command-shaped "
            "boundaries, pending handler-registration roster, teaching "
            "coverage, and live promise-vs-live contradictions. It is "
            "rendered from `atlas_integrity_audit` (a read-only "
            "operator-debug tool surface — not function-call backed). "
            "**When you hit a recipe gap (missing adapter, wrong recipe, "
            "unclear help), fire `yoke ouroboros field-note append` "
            "immediately — before retrying, before moving on.** "
            "Canonical long-form reference: "
            "`runtime/agents/_shared/ouroboros-field-note.md`; "
            "run `yoke ouroboros field-note append --help` for the "
            "worked failure modes and decision tree. Agents reach "
            "Yoke via the CLI; "
            "direct runtime.api imports from `python3 -c` are "
            "operator-debug surfaces only."
        ),
    },
    {
        "topic": "core",
        "purpose": "Inspect the selected Yoke control-plane authority",
        "recipe": "yoke db read \"SELECT 1\"",
        "notes": (
            "Read-only diagnostic SQL over the selected authority. Prefer "
            "registered `yoke <subcommand>` readers where they answer the "
            "question; use the source-dev/operator-debug `db_router query` "
            "fallback only for break-glass work inside a Yoke checkout. "
            "Never use ad-hoc imports — never `python -c \"from "
            "yoke_core.domain.worktree import get_db_path\"`. The retired "
            "`worktree paths db` mode is a guard that refuses root SQLite "
            "authority, not a connection recipe."
        ),
    },
    {
        "topic": "core",
        "purpose": "Read / write item sections (Progress Log, custom sections)",
        "recipe": (
            "yoke items section get YOK-N --section \"Progress Log\"\n"
            "yoke items section upsert YOK-N --section \"Progress Log\" "
            "--content-file PATH --ordering 200\n"
            "yoke items section delete YOK-N --section \"Progress Log\""
        ),
        "notes": (
            "Section name is case-sensitive. For Progress Log append-only "
            "updates, prefer `yoke items progress-log append YOK-N "
            "--headline X --content-file PATH`, which read-merge-writes "
            "atomically."
        ),
    },
    {
        "topic": "core",
        "purpose": "Backlog GitHub sync",
        "recipe": "yoke items github-sync YOK-N",
        "notes": (
            "Sync a backlog item or epic tasks to GitHub through the "
            "registered item function surface. Preserves item claim guards "
            "and project GitHub capability checks."
        ),
    },
    {
        "topic": "core",
        "purpose": "Backlog mutation family (CLI adapter)",
        "recipe": (
            "python3 -m yoke_core.api.service_client backlog-cli "
            "{add,update,batch-update,freeze,thaw,block,unblock,close,"
            "sync-labels,sync-body,rebuild-board,"
            "post-comment,get-next-id,list,dedup-search} ..."
        ),
        "notes": (
            "Operator-debug fallback for the backlog family, which has no "
            "`yoke` CLI adapter yet. Item id arg accepts PREFIX-N, or a bare "
            "project sequence with project context. "
            "`update` and `batch-update` take `<field> <value>` or "
            "`f1=v1 f2=v2` shapes; structured-field writes route through "
            "`items.structured_field.replace` — for those, prefer the "
            "canonical `yoke items structured-field replace` form. "
            "`freeze`/`thaw`/`block`/`unblock` use `items.scalar.update` "
            "internally."
        ),
    },
    {
        "topic": "core",
        "purpose": "Audited raw diagnostic read",
        "recipe": 'yoke db read "SELECT ..."',
        "notes": (
            "Read-only raw diagnostic surface. Prefer domain readers first, "
            "never use !=, use <>. Source-dev/operator-debug break-glass "
            "fallback: `python3 -m yoke_core.cli.db_router query "
            "\"SELECT ...\"`. Never call database CLIs directly."
        ),
    },
]


# Operational primitives (session id, function-call dispatch, script
# location, render reminder, file-cap discovery) and epic-task recipes
# live in siblings to keep this module under the 350-line authored-file
# cap. Merged into the canonical ``CORE_COMMANDS`` export so the
# renderer sees one list.
from yoke_core.domain.schema_api_context_commands_core_epic_task import (  # noqa: E402
    EPIC_TASK_COMMANDS,
)
from yoke_core.domain.schema_api_context_commands_core_operational import (  # noqa: E402
    OPERATIONAL_COMMANDS,
)


CORE_COMMANDS = CORE_COMMANDS + EPIC_TASK_COMMANDS + OPERATIONAL_COMMANDS
