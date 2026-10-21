"""Canonical source of truth for the Ouroboros field-note directive.

Every consumer (code imports, the ``yoke ouroboros field-note append --help``
renderer, the generated-block marker renderer, the doctor HC coherence
check, lint and guard denial footers) reads this module. No string
literals, no copies.

This module carries:

* ``DIRECTIVE``, ``BASIC_RECIPE``, and ``FOOTER`` — the short block rendered
  into AGENTS.md, skills, and the other generated directive surfaces.
* ``DENIAL_FOOTER`` — the shorter block appended to a lint or guard refusal.
* ``HELP_BODY`` — the ``yoke ouroboros field-note append --help`` description.
* The field-note category prefix (``CATEGORY_PREFIX``), closed ``--kind``
  enum (``KIND_VALUES``), and evidence length contract
  (``EVIDENCE_MAX_CHARS``).
"""

from __future__ import annotations


DIRECTIVE: str = (
    "File a field note each time a recipe, help text or refusal is wrong or "
    "missing, or you spot a bug outside your task — before moving on. If you "
    "already filed the same problem, add `--correlation-id <that note's id>`:"
)

BASIC_RECIPE: str = (
    "yoke ouroboros field-note append "
    "--kind <failed|new|unclear|observation> --evidence '...'"
)

FOOTER: str = f"{DIRECTIVE}\n{BASIC_RECIPE}"

DENIAL_FOOTER: str = (
    "If this fix is wrong, file a field note: "
    "yoke ouroboros field-note append --kind failed --evidence '...'"
)

HELP_BODY: str = (
    "File a field note each time a recipe, help text or refusal is wrong or "
    "missing, or you spot a bug outside your task — before moving on. Link a "
    "repeat with `--correlation-id <first note's id>`.\n"
    "\n"
    "Kinds:\n"
    "- failed: a recipe, help text or refusal gave a wrong result\n"
    "- new: no recipe or help covered what you needed\n"
    "- unclear: two surfaces disagree, or the guidance is ambiguous\n"
    "- observation: a bug or oddity outside your current task\n"
    "\n"
    "Correlated evidence is stored under the root note and excluded from "
    "unreviewed counts. "
    "Do not file progress or a routine recovery that worked."
)

CORRELATION_ID_HELP: str = (
    "Integer id of the first field note for this problem in this project. "
    "Find it with yoke ouroboros field-note list. Run labels are not root ids."
)


CATEGORY_PREFIX: str = "field-note-"
KIND_VALUES: tuple[str, ...] = ("failed", "new", "unclear", "observation")
EVIDENCE_MAX_CHARS: int = 4000


__all__ = (
    "DIRECTIVE",
    "BASIC_RECIPE",
    "FOOTER",
    "DENIAL_FOOTER",
    "HELP_BODY",
    "CORRELATION_ID_HELP",
    "KIND_VALUES",
    "EVIDENCE_MAX_CHARS",
)
