"""Remediation builders + adapter index for the
shell-quoted-function-payload lint.

Sibling module that owns the static heavy lifting so the lint hot path
stays under the 350-line authored-file budget. Surfaces:

* :func:`build_adapter_index` — read the CLI-adapter inventory and produce
  the ``"<module> <sub-path>" -> function_id`` map plus a parallel
  ``module -> sorted registered sub-paths`` map for the domain-level
  remediation copy.
* :func:`build_payload_remediation` / :func:`build_choreography_remediation`
  / :func:`build_domain_remediation` — denial bodies for the three
  classified shapes (precise function id, domain-only, hand-quoted JSON).

All three remediation builders consume ``REMEDIATION_API_FIRST`` from the
sibling messages module so the function-call surface naming stays in lock
step across guardrails.
"""

from __future__ import annotations

import re
import shlex
from typing import Dict, List, Tuple

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.lint_structured_field_transform_shell_messages import (
    REMEDIATION_API_FIRST,
)
from yoke_core.api.service_client_structured_api_adapter_inventory import (
    all_adapter_entries,
)


CONCRETE_READ_EXAMPLE: str = (
    "Narrow reads need no shell: `yoke items get PREFIX-N spec`, or one section "
    'with `yoke items get PREFIX-N body --section "## File Budget"`; the whole '
    "body with `yoke items get PREFIX-N body --full`."
)

_OVERRIDE_NOTE = (
    "Override `# lint:no-shell-json-payload-check` is audit-only; the rule "
    "still denies."
)


_ITEM_REF_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9]*-(?:\d+|N)")


def is_item_ref_token(token: str) -> bool:
    """True for a ``PREFIX-N`` item ref (or its ``PREFIX-N`` placeholder) in
    any project; such a token ends a command sub-path."""
    return bool(_ITEM_REF_TOKEN_RE.fullmatch(token or ""))


def _is_placeholder(token: str) -> bool:
    """Return True for inventory placeholder tokens that terminate a sub-path."""
    if not token:
        return True
    if token.startswith("<") or token.startswith("--") or token.startswith("-"):
        return True
    if is_item_ref_token(token):
        return True
    if token in {"PATH", "SID", "REASON", "RID"}:
        return True
    if "/" in token:
        return True
    if token in {"|", "&&", ";", "&"}:
        return True
    return False


def build_adapter_index() -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """Build the lookup map ``"<module> <sub-path>" -> function_id``.

    Walks each ``CLI_ADAPTERS`` entry, splits on shell quoting, finds the
    ``python(3) -m <module>`` prefix, and consumes every following token
    until the first placeholder (``<X>``, ``PREFIX-N``, ``--flag``, path-like).
    The collected tokens form the canonical sub-path under that module.

    Returns ``(by_key, subs_by_module)`` where:

    * ``by_key`` maps full ``"<module> <sub-path>"`` strings to the
      registered function id. ``setdefault`` preserves the first inventory
      entry on duplicate keys (e.g. ``items.scalar.update`` keeps
      ``"<module> items update"`` even though ``lifecycle.transition.execute``
      shares the same shape).
    * ``subs_by_module`` maps each module to a sorted list of its
      registered sub-paths (the part after ``"<module> "``). Empty
      sub-paths are recorded as ``""`` so a bare-module adapter would
      still be discoverable, though no current adapter uses that shape.
    """
    by_key: Dict[str, str] = {}
    subs_by_module: Dict[str, set] = {}
    for entry in all_adapter_entries():
        cli = entry.cli_invocation.strip()
        try:
            tokens = shlex.split(cli)
        except ValueError:
            continue
        if len(tokens) < 3:
            continue
        if tokens[0] not in ("python", "python3"):
            continue
        if tokens[1] != "-m":
            continue
        module = tokens[2]
        sub_tokens: List[str] = []
        for tok in tokens[3:]:
            if _is_placeholder(tok):
                break
            sub_tokens.append(tok)
        sub_path = " ".join(sub_tokens)
        key = f"{module} {sub_path}".rstrip()
        by_key.setdefault(key, entry.function_id)
        subs_by_module.setdefault(module, set()).add(sub_path)
    sorted_subs: Dict[str, List[str]] = {
        mod: sorted(subs) for mod, subs in subs_by_module.items()
    }
    return by_key, sorted_subs


def build_payload_remediation() -> str:
    body = (
        "BLOCKED: hand-quoted JSON payload to yoke_core.api.service_client "
        "(``printf '{...}'`` or ``--payload '<json>'``). Shell quoting breaks "
        "it and it skips FunctionCallRequest validation.\n\n"
        + REMEDIATION_API_FIRST
        + "\n\n"
        + CONCRETE_READ_EXAMPLE
        + "\n\n"
        + _OVERRIDE_NOTE
    )
    # Wrap here as defense-in-depth; the parent ``lint_shell_quoted_function_payload``
    # emit site also calls ``attach_check_id`` and the helper is
    # idempotent (double-append short-circuits to no-op).
    return attach_check_id(body, check_id="lint-shell-quoted-function-payload")


def build_choreography_remediation(adapter_key: str, function_id: str) -> str:
    lane_renderer = ""
    if function_id == "agents.render.run":
        lane_renderer = (
            "\n\nRender lane source bare, with an absolute root: "
            "`yoke dev run -- yoke agents render --target-root <absolute-checkout>`."
        )
    return (
        "BLOCKED: registry-covered Yoke CLI wrapped with shell "
        f"choreography. ``{adapter_key}`` (``{function_id}``) runs under redirection, "
        "a pipe, a heredoc, tee or variable capture. Run it bare; add "
        "``--json`` for the typed envelope.\n\n"
        + REMEDIATION_API_FIRST
        + lane_renderer
        + "\n\n"
        + CONCRETE_READ_EXAMPLE
        + "\n\n"
        + _OVERRIDE_NOTE
    )


def build_domain_remediation(
    module: str,
    command_tail: str,
    registered_subs: List[str],
) -> str:
    """Denial body for invocations in a known CLI domain with no registered sub.

    ``command_tail`` is the snippet of the operator's command that follows
    ``python3 -m <module>``; it is surfaced verbatim so the operator can
    see exactly what the lint parsed. ``registered_subs`` is the sorted
    list of sub-paths registered under that module (e.g. ``["items get",
    "items update"]`` for ``yoke_core.cli.db_router``).
    """
    tail_disp = command_tail.strip() or "(no subcommand)"
    if registered_subs:
        sub_lines = "\n".join(f"  - {sub}" for sub in registered_subs if sub)
        sub_block = "\nRegistered subcommands in this domain:\n" + sub_lines + "\n"
    else:
        sub_block = "\n"
    return (
        "BLOCKED: invocation in a Yoke CLI domain without a registered "
        "function-call adapter for that subcommand.\n\n"
        f"Detected module: ``{module}``. The ``{module}`` CLI domain is "
        f"not the agent path for ``{tail_disp}``. No function id covers "
        "this exact subcommand path; the current lint refuses to attribute "
        "the invocation to an unrelated function id."
        + sub_block
        + "\nUse the registered yoke adapter for the operation. If none exists, "
        "ask the control-plane operator to provide it; keep the original "
        "connection and request.\n\n" + CONCRETE_READ_EXAMPLE + "\n\n" + _OVERRIDE_NOTE
    )


def build_lifecycle_transition_note(
    adapter_key: str,
    function_id: str,
    cli_invocation: str,
) -> str:
    return (
        "NOTE: detected adapter "
        f"``{adapter_key}`` writes lifecycle status through the raw item "
        f"adapter. Canonical agent path: ``{cli_invocation}`` "
        f"(``{function_id}``), which evaluates every listed and structural "
        "gate of the item's pinned workflow definition."
    )


__all__ = [
    "CONCRETE_READ_EXAMPLE",
    "build_adapter_index",
    "build_payload_remediation",
    "build_choreography_remediation",
    "build_domain_remediation",
    "build_lifecycle_transition_note",
]
