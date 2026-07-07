"""Remediation builders + adapter index + mode resolver for the
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
* :func:`resolve_mode` — read the lint-config value
  (deny / warn). Lives here
  rather than in the lint hot path so the parent module stays under
  the line cap.

All three remediation builders consume ``REMEDIATION_API_FIRST`` from the
sibling messages module so the function-call surface naming stays in lock
step across guardrails.
"""

from __future__ import annotations

import shlex
from typing import Dict, List, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_structured_field_transform_shell_messages import (
    REMEDIATION_API_FIRST,
)
from yoke_core.api.service_client_structured_api_adapter_inventory import (
    all_adapter_entries,
)


CONCRETE_READ_EXAMPLE: str = (
    "Concrete copy-pasteable read examples (no shell choreography needed):\n\n"
    "  # Targeted read by structured field — small, fast, no pipes:\n"
    "  python3 -m yoke_core.cli.db_router items get YOK-N spec\n"
    "  python3 -m yoke_core.cli.db_router items get YOK-N spec --json\n\n"
    "  # Targeted read by body section — returns just the named ``## Heading``\n"
    "  # block. Exit 0 even when the heading is absent (advisory stays on\n"
    "  # stderr, stdout empty), so a missing section in a parallel tool-call\n"
    "  # batch does not cancel siblings:\n"
    "  python3 -m yoke_core.cli.db_router items get YOK-N body "
    "--section \"## File Budget\"\n\n"
    "  # Full rendered body (large items): write to a temp file, then read\n"
    "  # the file with your harness Read tool. The render auto-paginates so\n"
    "  # piping to head/tail is never the answer:\n"
    "  python3 -m yoke_core.domain.render_body N "
    "--output-file /tmp/yok-N-body.md"
)


def resolve_mode(payload: object | None = None) -> str:
    """Return ``deny`` (default) / ``warn`` from the single lint_config registry.

    Sourced from ``.yoke/lint-config`` via ``lint_config`` so this guard shares
    the one operator surface. Relayed hooks resolve from the client policy
    snapshot in the payload; local hooks fall back to the checked-out file.
    """
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(
        "lint_shell_quoted_function_payload", payload,
    )


def _is_placeholder(token: str) -> bool:
    """Return True for inventory placeholder tokens that terminate a sub-path."""
    if not token:
        return True
    if token.startswith("<") or token.startswith("--") or token.startswith("-"):
        return True
    if token.startswith("YOK-"):
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
    until the first placeholder (``<X>``, ``YOK-N``, ``--flag``, path-like).
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
        "BLOCKED: hand-quoted JSON payload to yoke_core.api.service_client.\n\n"
        "Detected pattern: a Bash command building a JSON envelope inline "
        "(via ``printf '{...}'`` or ``--payload '<json>'``) and piping or "
        "passing it to service_client. Hand-quoted JSON in shell is brittle "
        "(quoting/escaping/empty-content) and bypasses the type system that "
        "validates FunctionCallRequest envelopes.\n\n"
        + REMEDIATION_API_FIRST
        + "\n\n"
        + CONCRETE_READ_EXAMPLE
        + "\n\nOverride: add `# lint:no-shell-json-payload-check` to the "
        "command body (audit-only; the rule still denies in deny mode)."
    )
    # Wrap here as defense-in-depth; the parent ``lint_shell_quoted_function_payload``
    # emit site also calls ``append_field_note_footer`` and the helper is
    # idempotent (double-append short-circuits to no-op).
    return append_field_note_footer(body, rule_id="lint-shell-quoted-function-payload")


def build_choreography_remediation(adapter_key: str, function_id: str) -> str:
    return (
        "BLOCKED: registry-covered Yoke CLI wrapped with shell "
        f"choreography.\n\n"
        f"Detected adapter: ``{adapter_key}`` (covered by function id "
        f"``{function_id}``). The wrapping shell choreography (redirection, "
        "status probes, pipes, heredocs, tee, or shell-variable capture) "
        "is unnecessary terminal soup -- the adapter already supports "
        "``--json`` returning a typed FunctionCallResponse envelope, and "
        "the function-call surface is the cheaper escape hatch for "
        "machine callers.\n\n"
        + REMEDIATION_API_FIRST
        + "\n\n"
        + CONCRETE_READ_EXAMPLE
        + "\n\nOverride: add `# lint:no-shell-json-payload-check` to the "
        "command body (audit-only; the rule still denies in deny mode)."
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
        sub_block = (
            "\nRegistered subcommands in this domain:\n" + sub_lines + "\n"
        )
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
        + "\nIf this is a one-off operator/debug invocation, run it without "
        "shell choreography (no ``2>&1``, ``| tee``, ``$(...)`` capture, "
        "``; echo $?``). Mutation work belongs on the function-call surface "
        "— see ``docs/atlas.md`` and "
        "``runtime/api/service_client_structured_api_adapter_inventory.py`` "
        "for the registered adapters.\n\n"
        + CONCRETE_READ_EXAMPLE
        + "\n\nOverride: add `# lint:no-shell-json-payload-check` to the "
        "command body (audit-only; the rule still denies in deny mode)."
    )


def build_skill_orchestrated_note(
    adapter_key: str,
    function_id: str,
    canonical_skill: str,
    caveat: str,
) -> str:
    return (
        "NOTE: detected adapter "
        f"``{adapter_key}`` matches inventory entry ``{function_id}``, "
        "which is skill-orchestrated. Canonical agent path: "
        f"``{canonical_skill}``. Direct use is valid at the DB layer but "
        f"{caveat}"
    )


__all__ = [
    "CONCRETE_READ_EXAMPLE",
    "build_adapter_index",
    "build_payload_remediation",
    "build_choreography_remediation",
    "build_domain_remediation",
    "build_skill_orchestrated_note",
    "resolve_mode",
]
