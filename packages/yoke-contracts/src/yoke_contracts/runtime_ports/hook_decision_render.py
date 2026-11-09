"""Runtime interface for hook decision render."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class HookDecisionRender(Protocol):
    """Hook operations supplied by the executing adapter."""

    render_context_stdout: Any
    write_hook_output: Any


def get_hook_decision_render() -> HookDecisionRender:
    return cast(HookDecisionRender, load_port("hook_decision_render", HookDecisionRender))
