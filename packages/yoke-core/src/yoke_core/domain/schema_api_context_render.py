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


# Two rendering depths, because the packet serves two jobs that used to be
# fused. ``compact`` is the spine every session needs on arrival: the
# invariants, the canonical recipes, and the table/column listing that keeps
# an agent from confabulating a column name. ``full`` adds the long-form
# per-table and per-command notes — the worked wrong guesses and the
# operational caveats — which are worth reading at the moment they apply and
# are pure weight before it. Rendering the full body by default put 107,818
# bytes into an 8,192-byte channel, so the depth that arrives is the default
# and the depth that explains is one command away.
PACKET_DETAIL_COMPACT = "compact"
PACKET_DETAIL_FULL = "full"
PACKET_DETAILS: tuple[str, ...] = (PACKET_DETAIL_COMPACT, PACKET_DETAIL_FULL)


def packet_detail_pointer(role: str, topic: str) -> str:
    """Return the one line naming where a compact block's notes live."""
    return (
        f"_Compact depth. Per-table and per-command notes for this topic — "
        f"the caveats and the wrong guesses they correct — read with_ "
        f"`yoke packets render --role {role} --topic {topic} --detail full`."
    )


def _validate_detail(detail: str) -> str:
    if detail not in PACKET_DETAILS:
        raise ValueError(
            f"unknown packet detail {detail!r}; expected one of "
            f"{', '.join(PACKET_DETAILS)}"
        )
    return detail


def render_invariant_block() -> list[str]:
    return [
        "**Control-plane DB invariant:** Yoke control-plane authority "
        "is Postgres. Use registered `yoke <subcommand>` readers/writers "
        'for domain state, and `yoke db read "SELECT ..."` for raw '
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


def render_package_roots_block() -> list[str]:
    """Where a module actually lives, and how to look it up.

    An agent that greps for a module by guessing a directory named after
    the package finds nothing and concludes the code is missing. The
    roots are per-project, so this teaches the lookup rather than any one
    project's layout — the packet ships verbatim into every project Yoke
    installs into, where concrete paths from another repo would be worse
    than none.
    """
    return [
        "**Package roots (where a module actually lives):** an importable "
        "package name never implies a directory at the repo root, and the "
        "mapping is per-project. Resolve a module through the roots your "
        "project's `architecture_model` declares — read them with "
        "`yoke project-structure get --project P --family architecture_model "
        "--json` and consult its `package_roots`, which maps each package to "
        "roots labelled `package_under_root` (the package directory sits "
        "under the root) or `package_is_root` (the root directory IS the "
        "package, so the package name never appears on disk). One package "
        "may declare several roots; check every one before concluding a "
        "module is absent.",
    ]


def render_item_entry_surface_block() -> list[str]:
    """Workflow entry-surface doctrine taught in the ``core`` topic.

    Both the top-level ``main_agent`` packet and every Bash-capable
    ``*_agent`` packet inherit ``core`` so every Yoke agent sees this
    rule before creating work items. Enforcement owners:
    ``yoke_core.domain.item_entry_surface`` (typed surface + attestation)
    and the ``yoke items create`` adapter (scaffolding gate).
    """
    return [
        "**Work-item entry surfaces:** every create names a workflow and "
        "a typed entry surface (`web_form`, `cli`, `harness_skill`, or "
        "`promotion`). The selected immutable workflow version must allow "
        "that surface. File through `/yoke idea` (the skill-owned "
        "`harness_skill` path), `yoke dash TITLE INSTRUCTION`, or the "
        "laneless `yoke task TITLE INSTRUCTION`. "
        "`yoke items create` refuses a live harness session that is not "
        "in idea mode — the entry-surface token is caller-asserted and "
        "skips skill-side scaffolding. Operator/debug, `--dry-run`, and "
        "test isolation retain the low-level adapter. `/yoke idea` "
        "attests with `--execution-instructions-considered` after `yoke "
        "workflow execution-instruction resolve --workflow W --project P`; "
        "every non-web surface is refused without that attestation, and "
        "no adapter sets it for you.",
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
        "`{function, request_id, actor:{session_id,actor_id}, "
        "target:{kind,item_id|epic_id+task_num|qa_requirement_id|...}, "
        "payload, preconditions:{}, options:{}}`. `target.kind` ∈ "
        "`item|epic_task|qa_requirement|session|process`. "
        "`actor.session_id` is mandatory — handlers verify it against "
        "`work_claims`. `preconditions`/`options` are dicts (default "
        "`{}`). Scratch Python imports must prepend the repo root to "
        "`sys.path` or set `PYTHONPATH`; `/tmp` imports are not the "
        "agent path.",
        "",
        "",
        "**Registered write function ids** (dispatch through these, never a "
        "guessed name): "
        + ", ".join(f"`{fid}`" for fid in seed.AGENT_WRITE_FUNCTION_IDS)
        + ". Each has a CLI adapter under the reversible grammar "
        "(dots→spaces, underscores→hyphens).",
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
            f"`{name}`:{ftype}={default}" for name, ftype, default in meta["fields"]
        )
        out.append(
            f"- `{table}.{column}` — {fields_inline}. Validator: `{meta['validator']}`."
        )
    return out


def render_command_block(
    topic: str,
    *,
    role: str = "main_agent",
    detail: str = PACKET_DETAIL_COMPACT,
) -> list[str]:
    """Render one topic's wrapper commands at the requested depth.

    Both depths carry every command and its exact recipe — dropping a
    command would make the packet lie about what exists. Compact drops only
    the explanatory note beside each recipe.
    """
    _validate_detail(detail)
    rows = [
        command
        for command in seed.WRAPPER_COMMANDS
        if command["topic"] == topic
        and role in command.get("roles", (role,))
        and role not in command.get("exclude_roles", ())
    ]
    if not rows:
        return []
    out: list[str] = ["**Wrapper commands (prefer over raw SQL):**", ""]
    for row in rows:
        out.append(f"- _{row['purpose']}_")
        out.append(f"  - `{row['recipe']}`")
        if detail == PACKET_DETAIL_FULL and row.get("notes"):
            out.append(f"  - {row['notes']}")
    return out


def render_table_block(
    topic: str,
    resolve_columns: Callable[[str], list[tuple[str, str]]],
    *,
    detail: str = PACKET_DETAIL_COMPACT,
) -> list[str]:
    """Render one topic's schema cheat sheet at the requested depth.

    Both depths carry every table and every column name, which is the
    anti-confabulation surface the packet exists for. Compact drops the
    long-form note under each table.
    """
    _validate_detail(detail)
    tables = seed.TOPIC_TABLES.get(topic, ())
    if not tables:
        return []
    out: list[str] = ["**Schema cheat sheet:**", ""]
    for table in tables:
        cols = resolve_columns(table)
        col_str = ", ".join(name for name, _ in cols)
        notes = seed.CANONICAL_TABLES[table].get("notes", "")
        out.append(f"- **`{table}`** — `{col_str}`")
        if detail == PACKET_DETAIL_FULL and notes:
            out.append(f"  - {notes}")
    return out


__all__ = [
    "PACKET_DETAILS",
    "PACKET_DETAIL_COMPACT",
    "PACKET_DETAIL_FULL",
    "packet_detail_pointer",
    "render_invariant_block",
    "render_function_call_surface_block",
    "render_item_entry_surface_block",
    "render_json_nested_schema_block",
    "render_command_block",
    "render_table_block",
]
