"""Canonical source of truth for reading part of a command's answer.

Every consumer — per-subcommand ``--help`` epilogs, group help, the
``yoke --help`` listing, the ``main_agent`` startup block, and the inline
agent-rules teaching — reads this language from this module. No string
literals, no copies, so drift is structurally impossible upstream of the
renderer.

The decision this module serves happens *before* a command runs: the caller
knows it wants one field, one value, one row set, or the outcome of a long
run, and needs the shape that returns exactly that. Every registered read
already has one, and this module names it.

This module carries:

* :data:`DIRECTIVE`, :data:`COMPACT_RECIPES`, and :data:`FOOTER` — the short
  stanza that rides every ``--help`` block and the startup packet.
* :data:`RECIPES` and the :class:`ReadRecipe` shape — the worked catalog, one
  entry per thing a caller is after.
* :func:`format_recipes_for_help` — a pure renderer turning :data:`RECIPES`
  into the catalog block ``yoke --help`` prints. Deterministic, no I/O.

Tests in ``test_adapter_read_recipes`` lock the canonical text, the catalog,
and the renderer output shape.
"""

from __future__ import annotations

from typing import NamedTuple


DIRECTIVE: str = (
    "Want part of an answer? Ask the narrow question — "
    "every read has a shape that serves it."
)


class ReadRecipe(NamedTuple):
    """One thing a caller is after, and the invocation that serves it.

    Fields:
        want: what the caller is trying to get, phrased the way they would
            think of it at the moment they compose the command.
        recipe: the copy-paste-shaped invocation that returns exactly that.
        note: one sentence on why that shape is the one, and what else it
            accepts.
    """

    want: str
    recipe: str
    note: str


#: The three shapes that cover the routine case. Short enough to ride the
#: bottom of every ``--help`` block and the startup packet, which is the
#: point: the caller reads them while deciding how to invoke, not after.
COMPACT_RECIPES: tuple[tuple[str, str], ...] = (
    ("yoke <command> <arguments>", "the routine answer, already scoped"),
    ("yoke items get PREFIX-N status", "the fields you name"),
    ("tail -80 <raw-capture>", "the capture a watcher prints, once it exits"),
)


def _render_compact() -> str:
    width = max(len(recipe) for recipe, _ in COMPACT_RECIPES)
    lines = [DIRECTIVE]
    for recipe, gloss in COMPACT_RECIPES:
        lines.append(f"  {recipe.ljust(width)}  # {gloss}")
    return "\n".join(lines)


FOOTER: str = _render_compact()


#: One line for a startup block that can afford a pointer but not a stanza.
#: Every byte here rides every session start on every harness, so it names
#: the two shapes and sends the reader to the catalog for the rest.
STARTUP_READ_LINE: str = (
    "- Part of an answer — `yoke items get PREFIX-N status`; "
    "catalog `yoke --help`."
)


RECIPES: tuple[ReadRecipe, ...] = (
    ReadRecipe(
        want="The routine answer",
        recipe="yoke <command> <arguments>",
        note=(
            "Every registered read is already scoped to its routine answer, "
            "and one that holds something back names what it withheld and "
            "the command that serves it."
        ),
    ),
    ReadRecipe(
        want="One field of a record",
        recipe="yoke items get PREFIX-N status",
        note=(
            "A read that accepts field names serves exactly those fields; "
            'add --section "## Heading" to serve one block of a long text '
            "field."
        ),
    ),
    ReadRecipe(
        want="One value inside stored settings",
        recipe=(
            "yoke projects environment-settings get --project P "
            "--environment E --path key.path"
        ),
        note=(
            "A projection read takes the path to the value and serves that "
            "value."
        ),
    ),
    ReadRecipe(
        want="Specific rows",
        recipe=(
            'yoke db read "SELECT id, status FROM items '
            'ORDER BY id DESC LIMIT 20"'
        ),
        note=(
            "The columns, the filter, and the row count are all part of the "
            "question; --format lines serves pipe-delimited rows."
        ),
    ),
    ReadRecipe(
        want="The message waiting for this session",
        recipe="yoke messages list --state pending",
        note=(
            "The list serves one row per message; `yoke messages get "
            "MESSAGE-ID` then serves that one message."
        ),
    ),
    ReadRecipe(
        want="A long run's full output",
        recipe="tail -80 <raw-capture>",
        note=(
            "A watcher wrapper prints its raw capture path, so read that "
            "file once the run exits; a command with no wrapper is captured "
            'first with `_tmp=$(mktemp /tmp/yoke-cmd.XXXXXX); <command> '
            '>"$_tmp" 2>&1; _rc=$?` and the file read.'
        ),
    ),
    ReadRecipe(
        want="Everything a summary named as held back",
        recipe="yoke <command> <arguments> --full",
        note=(
            "The summary names this flag whenever it has more to serve, so "
            "the deliberate read is always one flag away from the routine "
            "one."
        ),
    ),
    ReadRecipe(
        want="The response envelope's structure",
        recipe="yoke <command> <arguments> --json",
        note=(
            "--json chooses the shape of the answer and pairs with every "
            "narrowing above."
        ),
    ),
)


def format_recipes_for_help() -> str:
    """Render the worked catalog for ``yoke --help``.

    Composes verbatim from :data:`RECIPES`, so a new entry flows into the
    listing with no extra wiring.
    """
    parts: list[str] = [DIRECTIVE, "", "The shape that serves each:", ""]
    for recipe in RECIPES:
        parts.append(f"  {recipe.want}")
        parts.append(f"    {recipe.recipe}")
        parts.append(f"    {recipe.note}")
        parts.append("")
    return "\n".join(parts).rstrip()


__all__ = (
    "DIRECTIVE",
    "COMPACT_RECIPES",
    "FOOTER",
    "STARTUP_READ_LINE",
    "ReadRecipe",
    "RECIPES",
    "format_recipes_for_help",
)
