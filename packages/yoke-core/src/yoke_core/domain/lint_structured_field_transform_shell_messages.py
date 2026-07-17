"""Remediation messages + recipe-residue patterns for the structured-field lints.

Single-source-of-truth module shared by:

* :mod:`yoke_core.domain.lint_structured_field_transform_shell` — uses
  :data:`REMEDIATION_TEXT` as its denial body and :data:`REMEDIATION_API_FIRST`
  to point operators at the function-call surface.
* :mod:`yoke_core.domain.lint_shell_quoted_function_payload` — uses
  :data:`REMEDIATION_API_FIRST` and the recipe-residue patterns to phrase
  its remediation.
* :mod:`yoke_core.engines.doctor_hc_terminal_recipe_residue` — scans
  :data:`RECIPE_RESIDUE_PATTERNS` against live guidance surfaces.

The constants live here (not inside either lint module) so the lint files
themselves stay small and so the shared vocabulary cannot drift between
the PreToolUse guardrails and the Doctor HC.
"""

from __future__ import annotations

from typing import Tuple

# Recipe-event FOOTER attribution: the structured-field transform denial-emit
# site lives in the sibling ``lint_structured_field_transform_shell.evaluate``,
# which applies ``append_field_note_footer`` to the assembled reason
# (``REMEDIATION_TEXT`` + ``REMEDIATION_API_FIRST``) right before the deny
# envelope is built. Imported here to keep the FOOTER coupling visible to
# anyone editing the templates below.
from yoke_core.domain.denial_field_note_footer import append_field_note_footer  # noqa: F401


REMEDIATION_TEXT = (
    "BLOCKED: structured-field transform via shell choreography.\n\n"
    "Detected pattern: read existing item content via `items get` or "
    "`sections get`, capture the content to a temp file / shell variable "
    "/ pipe-transformer, then write the transformed content back via "
    "`items update <field> --stdin` or `sections upsert --content-file`. "
    "This pattern hits quoting/empty-content friction and lacks "
    "idempotency.\n\n"
    "Use the Python-owned helper instead:\n\n"
    "  python3 -m yoke_core.domain.item_field_transform append-addendum"
    " \\\n"
    "    --item YOK-N --field <field> --heading \"<heading>\""
    " --source <name> --stdin\n\n"
    "For Progress Log appends (or any safe append to an item_sections "
    "row), use `section-append` instead of read-then-`sections upsert` "
    "choreography:\n\n"
    "  python3 -m yoke_core.domain.item_field_transform section-append"
    " \\\n"
    "    --item YOK-N --section \"Progress Log\" --headline \"<headline>\""
    " \\\n"
    "    --ordering 200 --source <name> --stdin\n\n"
    "For a full-field rewrite, write the complete intended content "
    "directly via `items update <field> --stdin` -- without the "
    "intermediate get + transform step.\n\n"
    "Suppression: `# lint:no-structured-transform-check` on the command "
    "body is audit-only (recorded as outcome=suppression_attempted) — the "
    "rule still denies."
)


REMEDIATION_API_FIRST: str = (
    "Function-call surface (preferred): dispatch through the typed registry "
    "from Python or HTTP — there is no shell-CLI meta-adapter for arbitrary "
    "function_id dispatch. For shell paths, use the named subcommand that "
    "covers the operation you need:\n\n"
    "  - Python: yoke_core.domain.yoke_function_dispatch.dispatch("
    "FunctionCallRequest(...))\n"
    "  - HTTP:   POST /api/functions/call (FunctionCallRequest JSON body)\n"
    "  - Shell:  use the named adapter below, for example "
    "`execute-structured-write`, `sections upsert`, `claim-work`, or "
    "`qa run-add`.\n\n"
    "Registered adapter inventory:\n"
    "  runtime/api/service_client_structured_api_adapter_inventory.py"
)


# Canonical banned-literal grep patterns the Doctor HC scans against.
#
# Each entry is a literal substring (not a regex). The HC matches occurrences
# in live guidance surfaces (.agents/skills/yoke/**, runtime/agents/**,
# runtime/harness/{claude,codex}/agents/**, docs/**, AGENTS.md, CLAUDE.md,
# CODEX.md) and FAILs when one appears outside the allowlist
# (docs/archive/**, docs/db-reference/**, runtime/api/**/test_*.py).
#
# These cover the historical terminal-soup recipe shapes the Yoke-functions
# epic retires:
#
# * ``printf '{...}' | python3 -m yoke_core.api.service_client ... --payload`` —
#   hand-quoted JSON payload to the service client. The function-call surface
#   builds a FunctionCallRequest in Python and dispatches via the registry.
# * ``--payload '<json>'`` argv form that smuggles literal JSON through shell.
# * ``has-capability ... 2>&1; echo $?`` — capability probe via shell-status
#   choreography. Function-covered replacement: ``projects.capability.has``
#   returns ``{success, result: {has: bool, ...}}`` directly.
# * ``items get ... | python3 -c`` — read-structured-field-then-transform
#   recipe. Covered by ``items.structured_field.append_addendum`` /
#   ``items.structured_field.section_upsert`` /
#   ``items.structured_field.section_append``.
# * ``mktemp /tmp/yoke-progress`` — Progress Log read-then-upsert
#   choreography. Covered by ``items.progress_log.append``.
# * Raw ``sqlite3 data/yoke.db`` / ``sqlite3 $YOKE_DB`` — read-only SQL
#   is allowed via the audited ``db_router query`` escape hatch only; typed
#   reads should use registered read functions.
RECIPE_RESIDUE_PATTERNS: Tuple[str, ...] = (
    # Hand-quoted JSON payload to service_client.
    "service_client functions-call --payload '{",
    "service_client functions-call --payload \"{",
    # Capability probe via shell status / redirection choreography.
    "projects has-capability yoke ephemeral-env 2>&1",
    "projects has-capability yoke ephemeral-env; echo $?",
    # Raw sqlite3 against the control-plane DB.
    "sqlite3 data/yoke.db",
    "sqlite3 $YOKE_DB",
    # items.get piped into in-line Python for transform.
    "items get ${ITEM} spec | python3 -c",
    "items get $ITEM spec | python3 -c",
    # Progress Log mktemp + read-then-upsert.
    "mktemp /tmp/yoke-progress",
)


__all__ = [
    "REMEDIATION_TEXT",
    "REMEDIATION_API_FIRST",
    "RECIPE_RESIDUE_PATTERNS",
]
