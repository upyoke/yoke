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
        f"_Schema and operation depth:_ "
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
        "**Control-plane DB invariant:** authority is Postgres, never a "
        "constructed worktree DB path. Use registered `yoke <subcommand>` "
        'and diagnostic `yoke db read "SELECT ..."`. Normal prod authority '
        "is HTTPS/API; retain it on retry. Escalate missing mutations to "
        "the control-plane operator with the operation and surfaces checked.",
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
        "**Package roots:** read "
        "`yoke project-structure get --project P --family architecture_model "
        "--json`. A package name never implies a directory at the repo root; "
        "one package may declare several roots. Check every `package_roots` "
        "entry: `package_under_root` "
        "holds the package directory; `package_is_root` is that directory.",
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
        "attests Before creation with `--execution-instructions-considered` after `yoke "
        "workflow execution-instruction resolve --workflow W --project P "
        "--full`; "
        "Non-web creation requires that attestation; adapters never set it.",
    ]


def render_function_call_surface_block() -> list[str]:
    """Registered write identities and canonical harness ids for CLI callers."""
    return [
        "**Registered writes** (use their `yoke` CLI adapters): "
        + ", ".join(f"`{fid}`" for fid in seed.AGENT_WRITE_FUNCTION_IDS)
        + ". CLI grammar: "
        "(dots→spaces, underscores→hyphens).",
        "Adapters build the function-call envelope: `actor.session_id` "
        "binds the harness; optional `actor_id` resolves server-side and "
        "must agree if supplied. `target` selects the subject; `preconditions` "
        "guard the write and `options` carry execution choices.",
        "",
        "**`harness_sessions.executor`:** `claude-code | codex | cursor`; "
        "surface variants normalize to these ids.",
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
    startup: bool = False,
) -> list[str]:
    """Render one topic's wrapper commands at the requested depth.

    Topic reads carry the complete role-aware catalog at both depths.
    Startup selects rows whose audience acts on them now; every retained
    recipe stays exact. Compact omits expanded notes.
    """
    _validate_detail(detail)
    rows = [
        command
        for command in seed.WRAPPER_COMMANDS
        if command["topic"] == topic
        and role in command.get("roles", (role,))
        and role not in command.get("exclude_roles", ())
        and (not startup or role in command.get("startup_roles", (role,)))
    ]
    if not rows:
        return []
    out: list[str] = ["**Wrapper commands (prefer over raw SQL):**", ""]
    for row in rows:
        out.append(f"- _{row['purpose']}_")
        for command in recipe_commands(str(row["recipe"])):
            out.append(f"  - `{command}`")
        if detail == PACKET_DETAIL_FULL and row.get("notes"):
            out.append(f"  - {row['notes']}")
    return out


def recipe_commands(recipe: str) -> list[str]:
    """Split a recipe into one entry per command it actually teaches.

    A recipe row may hold several independent commands separated by newlines,
    or one command continued across lines by a trailing backslash or an open
    quote. Emitting the whole row as a single inline-code span conflates the
    two: a span containing newlines is not code to any markdown reader, it
    leaves a stray backtick on the closing line, and it hides each command
    from the recipe extractor that audits whether a taught command resolves
    to a registered surface — so a real recipe can go unaudited by formatting
    alone.

    Independent commands therefore each get their own span, while a continued
    command keeps its newlines inside one span, because that is the single
    command it is.
    """
    commands: list[str] = []
    pending: list[str] = []
    for line in recipe.split("\n"):
        pending.append(line)
        joined = "\n".join(pending)
        if line.rstrip().endswith("\\") or joined.count('"') % 2:
            continue
        commands.append(joined)
        pending = []
    if pending:
        commands.append("\n".join(pending))
    return [command for command in commands if command.strip()]


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
    "recipe_commands",
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
