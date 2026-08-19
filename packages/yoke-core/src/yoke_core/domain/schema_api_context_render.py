"""Block renderers consumed by :mod:`schema_api_context`.

Sibling of :mod:`schema_api_context`. Holds the per-block render
helpers — invariant header, function-call surface stanza, JSON
nested-field schemas, command block, table block — so the top-level
renderer module stays small and focused on the public CLI / drift /
size-budget surface.

Pure string formatting only — no DB I/O. The table block takes a
``resolve_columns`` callback so callers can plug in live-introspection
or seed-only column resolution as needed.
"""

from __future__ import annotations

from typing import Callable

from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.schema_api_context_json_schemas import (
    ACCESS_PATTERN_NOTE,
    JSON_NESTED_SCHEMAS,
)
from yoke_core.domain.schema_api_context_package_roots import (
    LAYOUT_GLOSS,
    PackageRoots,
)


def render_invariant_block() -> list[str]:
    return [
        "**Control-plane DB invariant:** Yoke control-plane authority "
        "is Postgres. Use registered `yoke <subcommand>` readers/writers "
        "for domain state, and `yoke db read \"SELECT ...\"` for raw "
        "diagnostic SELECTs. Do not "
        "construct DB file paths from `$PWD`, `CLAUDE_PROJECT_DIR`, or "
        "linked worktree paths. Product/normal prod reads stay on "
        "wrapped HTTPS/API-backed surfaces (`yoke <subcommand>` and "
        "`yoke db read`); do not retry by switching to a local-Postgres "
        "prod env. Local-Postgres surfaces (`db_router query`, doctor, "
        "capability resolvers, module-form tools) are source-dev/admin or "
        "audited break-glass only; use `YOKE_ENV=<env>-db-admin` / "
        "`--env <env>-db-admin` only when a sanctioned admin recipe explicitly "
        "requires direct DB authority.",
    ]


def render_package_roots_block(roots: PackageRoots) -> list[str]:
    """Where each importable package's source lives, from *roots*.

    Taught in the ``core`` topic so every role sees it: an agent that
    greps for a module by guessing a repo-root directory named after the
    package finds nothing and concludes the code is missing. The values
    come from the resolver rather than this prose so they track the
    project's declared layout instead of drifting beside it.
    """
    if not roots:
        return []
    declared = "; ".join(
        f"`{package}` -> "
        + ", ".join(f"`{root}` ({layout})" for root, layout in entries)
        for package, entries in sorted(roots.items())
    )
    gloss = "; ".join(
        f"`{layout}` = {text}" for layout, text in sorted(LAYOUT_GLOSS.items())
    )
    return [
        "**Package roots (where a module actually lives):** an importable "
        "package name never implies a directory at the repo root — resolve "
        "a module through the roots the project's `architecture_model` "
        f"declares. {gloss}. Declared: {declared}.",
    ]


def render_item_entry_surface_block() -> list[str]:
    """Workflow entry-surface doctrine taught in the ``core`` topic.

    Both the top-level ``main_agent`` packet and every Bash-capable
    ``*_agent`` packet inherit ``core`` so every Yoke agent sees this
    rule before creating work items. Enforcement owner:
    ``yoke_core.domain.item_entry_surface``.
    """
    return [
        "**Work-item entry surfaces:** every create names a workflow and "
        "a typed entry surface (`web_form`, `cli`, `harness_skill`, or "
        "`promotion`). The selected immutable workflow version must allow "
        "that surface. `/yoke idea` uses `yoke items create ... "
        "--entry-surface harness_skill`; dry-run and test-isolated DB "
        "targets may omit the surface.",
    ]


def render_function_call_surface_block() -> list[str]:
    """Function-call dispatch surface + harness_id enum.

    Lives at the top of the ``core`` topic so every agent sees the
    canonical envelope shape before reaching for any CLI adapter.
    ``harness_id`` enum is named here so agents do not confabulate
    ``claude_code`` / ``codex_desktop`` when inspecting
    ``harness_sessions.executor``.
    """
    return [
        "**Function-call surface (canonical mutation path):** "
        "`yoke_core.domain.yoke_function_dispatch.dispatch` "
        "validates a `FunctionCallRequest` from "
        "`yoke_contracts.api.function_call` and returns a "
        "`FunctionCallResponse`. Minimal envelope: "
        '`{function, request_id, actor:{session_id,actor_id}, '
        "target:{kind,item_id|epic_id+task_num|qa_requirement_id|...}, "
        "payload, preconditions:{}, options:{}}`. `target.kind` ∈ "
        "`item|epic_task|qa_requirement|session|process`. "
        "`actor.session_id` is mandatory — handlers verify it against "
        "`work_claims`. `preconditions`/`options` are dicts (default "
        "`{}`). Scratch Python imports must prepend the repo root to "
        "`sys.path` or set `PYTHONPATH`; `/tmp` imports are not the "
        "agent path.",
        "",
        "**`harness_id` enum:** `claude-code | codex | cursor` (on "
        "`harness_sessions.executor`). Variants `claude-desktop` / "
        "`claude-vscode` / `codex-desktop` / `cursor-desktop` / `cursor-cli` "
        "collapse to these canonical ids in the agent-context render path.",
    ]


def render_json_nested_schema_block(topic: str) -> list[str]:
    """Per-topic JSON nested-field schema block.

    Lives under the schema cheat sheet for each topic and names the
    inner-field shape of every TEXT-with-JSON column the topic
    surfaces. Agents read this instead of guessing nested keys.
    """
    entries = [
        (table, column, meta)
        for (table, column), meta in JSON_NESTED_SCHEMAS.items()
        if meta["topic"] == topic
    ]
    if not entries:
        return []
    out: list[str] = [
        f"**JSON-nested-field schemas** (_{ACCESS_PATTERN_NOTE}_):",
    ]
    for table, column, meta in entries:
        fields_inline = ", ".join(
            f"`{name}`:{ftype}={default}"
            for name, ftype, default in meta["fields"]
        )
        out.append(
            f"- `{table}.{column}` — {fields_inline}. "
            f"Validator: `{meta['validator']}`."
        )
    return out


def render_command_block(topic: str) -> list[str]:
    rows = [c for c in seed.WRAPPER_COMMANDS if c["topic"] == topic]
    if not rows:
        return []
    out: list[str] = ["**Wrapper commands (prefer over raw SQL):**", ""]
    for row in rows:
        out.append(f"- _{row['purpose']}_")
        out.append(f"  - `{row['recipe']}`")
        if row.get("notes"):
            out.append(f"  - {row['notes']}")
    return out


def render_table_block(
    topic: str,
    resolve_columns: Callable[[str], list[tuple[str, str]]],
) -> list[str]:
    tables = seed.TOPIC_TABLES.get(topic, ())
    if not tables:
        return []
    out: list[str] = ["**Schema cheat sheet:**", ""]
    for table in tables:
        cols = resolve_columns(table)
        col_str = ", ".join(name for name, _ in cols)
        notes = seed.CANONICAL_TABLES[table].get("notes", "")
        out.append(f"- **`{table}`** — `{col_str}`")
        if notes:
            out.append(f"  - {notes}")
    return out


__all__ = [
    "render_invariant_block",
    "render_function_call_surface_block",
    "render_item_entry_surface_block",
    "render_json_nested_schema_block",
    "render_command_block",
    "render_table_block",
]
