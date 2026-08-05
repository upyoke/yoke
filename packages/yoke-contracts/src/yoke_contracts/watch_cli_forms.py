"""Canonical ``yoke watch <kind>`` command forms for the watcher wrappers.

The watcher wrappers live in ``yoke_core.tools`` but their agent-facing
invocation is a ``yoke`` subcommand, so two packages need the same
spelling: the CLI builds its token table from this map, and the wrappers
print it inside ``--print-streaming-pair`` output. Contracts is the one
package both may import statically, so the mapping lives here.

The module form (``python3 -m yoke_core.tools.watch_pytest``) stays
callable as the operator-debug fallback; it is not a form this module
teaches.
"""

from __future__ import annotations

# Wrapper module -> the ``yoke`` CLI tokens that invoke it.
WATCH_CLI_TOKENS: dict[str, tuple[str, ...]] = {
    "yoke_core.tools.watch_pytest": ("watch", "pytest"),
    "yoke_core.tools.watch_doctor": ("watch", "doctor"),
    "yoke_core.tools.watch_merge": ("watch", "merge"),
    "yoke_core.tools.watch_deploy": ("watch", "deploy"),
    "yoke_core.tools.watch_qa_case": ("watch", "qa-case"),
    "yoke_core.tools.watch_tail": ("watch", "tail"),
}


def cli_form(wrapper_module: str) -> str | None:
    """Return the ``yoke watch <kind>`` invocation, or ``None`` if unmapped.

    Watchers without a CLI adapter (``watch_advance``, ``watch_lifecycle``,
    ``watch_session_offer``) return ``None``; callers keep their module
    invocation for those.
    """
    tokens = WATCH_CLI_TOKENS.get(wrapper_module)
    if tokens is None:
        return None
    return "yoke " + " ".join(tokens)


__all__ = ["WATCH_CLI_TOKENS", "cli_form"]
