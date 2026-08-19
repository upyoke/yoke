"""Reject specs that prescribe a guard-blocked agent command shape."""

from __future__ import annotations

import re
from typing import List

CODE = "BLOCKED_AGENT_COMMAND_SHAPE"

_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_INLINE_RE = re.compile(r"`([^`]+)`")
_PYTHON_C_RE = re.compile(
    r"(?:python3?|yoke\s+dev\s+run\s+--\s+python3?)\s+-c\b",
    re.IGNORECASE,
)
_FORBIDDEN_IMPORT_RE = re.compile(
    r"(?:from|import)\s+"
    r"(?:yoke_core|yoke_cli|yoke_harness|"
    r"runtime(?:\.(?:api|harness|agents))?)"
)


def _command_spans(spec_text: str) -> List[str]:
    text = spec_text or ""
    spans = [match.group(1) for match in _FENCE_RE.finditer(text)]
    spans.extend(match.group(1) for match in _INLINE_RE.finditer(text))
    return spans


def verify_done_means_agent_shape(spec_text: str) -> list:
    """Flag fenced or backticked ``python3 -c`` Yoke-import prescriptions."""
    from yoke_core.domain.idea_readiness_check import Issue

    for span in _command_spans(spec_text):
        if _PYTHON_C_RE.search(span) and _FORBIDDEN_IMPORT_RE.search(span):
            return [Issue(
                code=CODE,
                message=(
                    "Spec prescribes a python3 -c import of a Yoke "
                    "implementation symbol as a command to run. "
                    "lint-no-agent-runtime-api-import-from-c refuses "
                    "that shape, so the item cannot be verified by its "
                    "own done-means."
                ),
                remediation=(
                    "Name a guard-permitted command: `yoke <subcommand>`, "
                    "`yoke watch pytest -- ...`, or `yoke dev run --` "
                    "with a module form (`python3 -m ...`) — never "
                    "`python3 -c` importing yoke_core / yoke_cli / "
                    "yoke_harness / runtime.api."
                ),
            )]
    return []


__all__ = ["CODE", "verify_done_means_agent_shape"]
