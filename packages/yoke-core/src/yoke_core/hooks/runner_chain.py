"""Chain resolution and the dry-run view of it for the hook runner.

Which modules an event runs is one question, answered here for both callers
that ask it: :func:`yoke_core.hooks.runner.run_event`, which then dispatches
the resolved chain, and ``--dry-run``, which prints it instead. Keeping the
resolution beside its own rendering leaves the runner module holding
dispatch alone.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.hook_runner.chain_registry import chain_for
from yoke_contracts.hook_runner.hook_ordering import matchers_for
from yoke_core.hooks.adapter_capability import AdapterCapability


__all__ = [
    "apply_omissions",
    "render_dry_run",
    "resolve_chain",
    "resolve_matcher",
]


def resolve_matcher(event_name: str, payload: dict[str, Any]) -> Optional[str]:
    """Return the per-tool matcher an event's chain is keyed by, if any."""
    if event_name in {"PreToolUse", "PostToolUse"}:
        tool_name = payload.get("tool_name")
        if isinstance(tool_name, str) and tool_name:
            return tool_name
    if event_name == "apply_patch":
        return "apply_patch"
    return None


def apply_omissions(
    chain: list[str],
    *,
    event_name: str,
    capability: AdapterCapability,
) -> list[str]:
    """Drop the modules this adapter declares it does not run for *event_name*."""
    omitted: frozenset[str] = frozenset()
    if event_name == "apply_patch":
        omitted = capability.apply_patch_chain_omissions
    elif event_name == "PreToolUse":
        omitted = capability.pretool_omissions
    if not omitted:
        return chain
    return [m for m in chain if m not in omitted]


def resolve_chain(
    event_name: str,
    matcher: Optional[str],
    capability: AdapterCapability,
) -> list[str]:
    """Return the ordered modules this adapter runs for the event."""
    return apply_omissions(
        chain_for(event_name, matcher),
        event_name=event_name,
        capability=capability,
    )


def _format_chain(chain: list[str], capability: AdapterCapability) -> str:
    if not chain:
        return ""
    lines = [
        f"{'[subproc]' if mid in capability.subprocess_modules else '[typed]'} {mid}"
        for mid in chain
    ]
    return "\n".join(lines) + "\n"


def render_dry_run(
    event_name: str,
    matcher: Optional[str],
    capability: AdapterCapability,
) -> str:
    """Print the dry-run chain. With no resolved matcher on a tool-shaped
    event, enumerate every registered matcher so the operator sees the
    full per-tool layout.
    """
    if matcher is None and event_name in {"PreToolUse", "PostToolUse"}:
        sections: list[str] = []
        for tool in matchers_for(event_name) or []:
            body = _format_chain(
                resolve_chain(event_name, tool, capability), capability
            )
            if body:
                sections.append(f"# {event_name}:{tool}\n{body.rstrip()}")
        return "\n\n".join(sections) + "\n" if sections else ""
    return _format_chain(resolve_chain(event_name, matcher, capability), capability)
