"""Shared remediation messages for the structured-field lints.

Single-source-of-truth module shared by:

* :mod:`yoke_core.domain.lint_structured_field_transform_shell` — uses
  :data:`REMEDIATION_TEXT` as its denial body and :data:`REMEDIATION_API_FIRST`
  to point operators at the function-call surface.
* :mod:`yoke_core.domain.lint_shell_quoted_function_payload` — uses
  :data:`REMEDIATION_API_FIRST` to phrase its remediation.

The constants live here (not inside either lint module) so the lint files
themselves stay small and their recovery messages stay consistent.
"""

from __future__ import annotations

# The denial-emit site lives in the sibling
# ``lint_structured_field_transform_shell.evaluate``, which attaches the
# check-id line to the assembled reason (``REMEDIATION_TEXT`` +
# ``REMEDIATION_API_FIRST``) right before the deny envelope is built. The
# templates below carry the recovery text only.


REMEDIATION_TEXT = (
    "BLOCKED: structured-field transform via shell choreography.\n\n"
    "Detected pattern: read existing item content via `items get` or "
    "`sections get`, capture the content to a temp file / shell variable "
    "/ pipe-transformer, then write the transformed content back via "
    "`items update <field> --stdin` or `sections upsert --content-file`. "
    "This pattern hits quoting/empty-content friction and lacks "
    "idempotency.\n\n"
    "Use the registered additive adapter instead:\n\n"
    "  yoke items structured-field append-addendum PREFIX-N"
    " --field FIELD --heading HEADING"
    " --source <name> --stdin\n\n"
    "For a Progress Log checkpoint, use the registered append instead of "
    "read-then-write choreography:\n\n"
    "  yoke items progress-log append PREFIX-N --headline HEADLINE --stdin\n\n"
    "For a full-field rewrite, write the complete intended content "
    "directly via `yoke items structured-field replace PREFIX-N --field FIELD --stdin` without the "
    "intermediate get + transform step.\n\n"
    "Suppression: `# lint:no-structured-transform-check` on the command "
    "body is audit-only (recorded as outcome=suppression_attempted) — the "
    "rule still denies."
)


REMEDIATION_API_FIRST: str = (
    "Use the registered yoke adapter on the selected connection. Run "
    "yoke --help for its command family and --help for flags. If no adapter "
    "serves the operation, ask the control-plane operator to provide it; "
    "retain the request and current connection. Direct database, runtime "
    "imports and HTTP requests are not an agent recovery path."
)


__all__ = [
    "REMEDIATION_TEXT",
    "REMEDIATION_API_FIRST",
]
