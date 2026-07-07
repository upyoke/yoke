"""Canonical source of truth for the Ouroboros field-note directive.

Every consumer (code imports, the ``yoke ouroboros field-note append --help``
renderer, the generated-block marker renderer for runtime markers, the doctor
HC coherence check, lint denial footers, packet renderers) reads the directive
language from this module. No string literals, no copies — drift becomes
structurally impossible upstream of the renderer.

The field-note channel covers two scopes in one fast-capture surface:

* **Recipe gaps** — a recipe the agent followed produced the wrong result, no
  recipe covered the workflow at all, or two teaching surfaces contradicted
  each other.
* **Minor bug observations** — a stale doc reference, an orphan row from a
  race, surprising behavior in an unrelated surface noticed during current
  work. Not in current scope. Not worth a full ticket today.

This module carries:

* The canonical directive constants (``DIRECTIVE``, ``BASIC_RECIPE``,
  ``HELP_POINTER``, ``FOOTER``) and the ``FailureMode`` shape — pure data.
* The closed ``--kind`` enum (``KIND_VALUES``) plus the operator-facing
  definition of the ``observation`` kind (``KIND_OBSERVATION_DEFINITION``).
* ``format_failure_modes_for_help`` — a pure renderer that turns
  ``FAILURE_MODES`` into the ``yoke ouroboros field-note append --help``
  description string. Pure function, deterministic, no I/O.
* ``HELP_BODY`` — the full ``--help`` body string composed at module load
  from the worked-mode catalog, the decision tree, the canonical vocabulary,
  and the inline-short footer.

Tests in ``test_field_note_text`` lock the canonical text, the worked-mode
catalog, the decision tree, and the renderer output shape.
"""

from __future__ import annotations

from typing import NamedTuple


DIRECTIVE: str = (
    "When you hit a recipe gap or notice a minor bug not worth a ticket, "
    "file a field-note immediately — before retrying, before moving on."
)

BASIC_RECIPE: str = (
    "yoke ouroboros field-note append "
    "--kind <failed|new|unclear|observation> --evidence '...'"
)

HELP_POINTER: str = (
    "Run `yoke ouroboros field-note append --help` "
    "for the worked failure modes and decision tree."
)

FOOTER: str = f"{DIRECTIVE}\n{BASIC_RECIPE}\n{HELP_POINTER}"


KIND_VALUES: tuple[str, ...] = ("failed", "new", "unclear", "observation")


KIND_OBSERVATION_DEFINITION: str = (
    "minor bug, surprise, or stale reference noticed during unrelated work. "
    "Not in current scope. Not worth a ticket today."
)


class FailureMode(NamedTuple):
    """One concrete failure mode that should trigger an immediate field-note.

    Fields:
        kind: the ``--kind`` enum value the producer should pass
            (``failed``, ``new``, ``unclear``, or ``observation``).
        title: one-line label naming the failure mode.
        example_evidence: a copy-paste-shaped ``--evidence`` string showing the
            level of concreteness expected.
        when_to_fire: the trigger condition — when the producer should reach for
            this kind rather than push past the gap.
    """

    kind: str
    title: str
    example_evidence: str
    when_to_fire: str


FAILURE_MODES: tuple[FailureMode, ...] = (
    FailureMode(
        kind="new",
        title="Recipe missing",
        example_evidence=(
            "No recipe covers narrowing a path claim by drop-paths; "
            "had to grep service_client for the flag."
        ),
        when_to_fire=(
            "Agent needed a workflow with no existing recipe coverage — "
            "no skill, packet, or --help surface taught it."
        ),
    ),
    FailureMode(
        kind="new",
        title="No help info accessible",
        example_evidence=(
            "`yoke claims path register --help` returns no body, just usage line."
        ),
        when_to_fire=(
            "`--help` returns nothing, a stub, or no body — the producer cannot "
            "self-orient without leaving the CLI."
        ),
    ),
    FailureMode(
        kind="failed",
        title="Recipe wrong / needs tweak",
        example_evidence=(
            "R-CL-03 path-claim-narrow taught --remove; actual flag is --drop-paths."
        ),
        when_to_fire=(
            "Recipe was taught but produced the wrong result when followed literally "
            "(wrong flag, wrong arg order, wrong subcommand)."
        ),
    ),
    FailureMode(
        kind="failed",
        title="Help info wrong",
        example_evidence=(
            "`yoke items get --help` example shows `--field body`; "
            "real field name is `body` without the flag."
        ),
        when_to_fire=(
            "`--help` example doesn't match real behavior — running the example "
            "verbatim exits non-zero or returns the wrong shape."
        ),
    ),
    FailureMode(
        kind="failed",
        title="Lint or guard blocked something that should be allowed",
        example_evidence=(
            "lint_session_cwd denied a write under an OS-temp scratch path; "
            "free-path allowlist should cover /tmp."
        ),
        when_to_fire=(
            "A lint or guardrail refused a legitimate operation, forcing a "
            "workaround that the rule did not intend to require."
        ),
    ),
    FailureMode(
        kind="unclear",
        title="Conflicting recipes",
        example_evidence=(
            "skill body teaches `db_router items update`; AGENTS.md teaches "
            "`items.structured_field.replace`. Both fire on the same surface."
        ),
        when_to_fire=(
            "Two teaching surfaces give contradictory forms for the same operation."
        ),
    ),
    FailureMode(
        kind="unclear",
        title="Block or error message could be more useful",
        example_evidence=(
            "path-claim-register exited with 'overlap detected' — did not name "
            "the holding session, item, or paths in the overlap set."
        ),
        when_to_fire=(
            "A block or error message left out concrete remediation context — "
            "the holding session, the missing path, the next command to run."
        ),
    ),
    FailureMode(
        kind="observation",
        title="Stale doc reference noticed during unrelated work",
        example_evidence=(
            "docs/lifecycle.md still references `polish-implementation`; "
            "the live status name is `polishing-implementation`."
        ),
        when_to_fire=(
            "Reading a doc, skill, or packet during unrelated work surfaced a "
            "stale or wrong reference. Not in current scope, not worth a ticket."
        ),
    ),
    FailureMode(
        kind="observation",
        title="Orphan row or stale state noticed during unrelated work",
        example_evidence=(
            "Saw a `work_claims` row with `released_at IS NULL` whose owning "
            "session ended 3 days ago; no live session is operating on it."
        ),
        when_to_fire=(
            "Stumbled on durable state (DB row, file, lease) that looks stale "
            "but is not blocking the current item. Capture for later cleanup."
        ),
    ),
    FailureMode(
        kind="observation",
        title="Surprising behavior in an unrelated surface",
        example_evidence=(
            "`yoke board` rendered an item with empty title where the DB row "
            "has a non-empty title column — render path may be stripping it."
        ),
        when_to_fire=(
            "An unrelated surface behaved in a way that was surprising but did "
            "not block current work. Not worth diagnosing today."
        ),
    ),
)


_DECISION_TREE: str = (
    "Decision tree (pick the matching --kind):\n"
    "  Did you observe a minor bug or surprise unrelated to current scope?\n"
    "    yes -> --kind observation  (stale doc reference, orphan row, surprising\n"
    "                                behavior in an unrelated surface; not in\n"
    "                                current scope, not worth a ticket today)\n"
    "    no  -> Did the recipe exist?\n"
    "             no  -> --kind new       (no skill, packet, --help, or doc\n"
    "                                     taught it)\n"
    "             yes -> Did it produce the right result when followed\n"
    "                    literally?\n"
    "                      no  -> --kind failed  (wrong flag, wrong arg order,\n"
    "                                             wrong subcommand, --help\n"
    "                                             example wrong, lint blocked\n"
    "                                             a legitimate operation)\n"
    "                      yes -> Are there conflicting / unclear teachings?\n"
    "                               yes -> --kind unclear\n"
    "                               no  -> no field-note needed"
)


_CANONICAL_VOCABULARY: str = (
    "Canonical --kind vocabulary:\n"
    "  failed      — recipe was taught but produced the wrong result.\n"
    "  new         — workflow had no recipe coverage at all.\n"
    "  unclear     — two teaching surfaces contradicted each other, or a\n"
    "                block / error message left out remediation context.\n"
    f"  observation — {KIND_OBSERVATION_DEFINITION}"
)


_PREAMBLE: str = (
    "Append a structured field-note to the Ouroboros learning channel.\n"
    "\n"
    "Field-notes cover two scopes in one fast-capture surface:\n"
    "  - Recipe gaps: a recipe produced the wrong result, no recipe covered\n"
    "    the workflow, or two teaching surfaces contradicted each other.\n"
    "  - Minor bug observations: stale doc reference, orphan row from a race,\n"
    "    surprising behavior in an unrelated surface. Not in current scope.\n"
    "    Not worth a full ticket today.\n"
)


def format_failure_modes_for_help() -> str:
    """Render the worked failure modes + decision tree + --kind vocabulary.

    Used by ``yoke ouroboros field-note append --help`` and any other
    surface that wants the full operator-facing teaching block. The output
    composes verbatim from ``FAILURE_MODES``, ``_DECISION_TREE``, and
    ``_CANONICAL_VOCABULARY`` so drift in the underlying data flows into
    every consumer with no extra wiring.
    """
    parts: list[str] = [
        "Fire one field-note per failure mode or observation you hit —",
        "before retrying, before moving on. The worked failure modes:",
        "",
    ]
    for idx, mode in enumerate(FAILURE_MODES, start=1):
        parts.append(f"{idx}. [{mode.kind}] {mode.title}")
        parts.append(f"   When to fire: {mode.when_to_fire}")
        parts.append(f"   Example evidence: {mode.example_evidence}")
        parts.append("")
    parts.append(_DECISION_TREE)
    parts.append("")
    parts.append(_CANONICAL_VOCABULARY)
    return "\n".join(parts)


HELP_BODY: str = f"{_PREAMBLE}\n{format_failure_modes_for_help()}\n\n{FOOTER}"


__all__ = (
    "DIRECTIVE",
    "BASIC_RECIPE",
    "HELP_POINTER",
    "FOOTER",
    "KIND_VALUES",
    "KIND_OBSERVATION_DEFINITION",
    "FailureMode",
    "FAILURE_MODES",
    "format_failure_modes_for_help",
    "HELP_BODY",
)
