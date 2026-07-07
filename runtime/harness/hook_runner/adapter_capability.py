"""Per-harness capability descriptor the runner reads at dispatch time.

`AdapterCapability` is the only thing a new harness must author to plug into
the shared runner. It carries the harness identity, the events it subscribes
to, the payload parser + decision renderer for its wire format, the chain
omissions that express harness asymmetries (e.g. Codex skips
`lint_write_path` on `apply_patch`), and `subprocess_modules` — the carve-out
set the runner uses to dispatch a policy via `subprocess.run` instead of
`importlib + evaluate(record)`. Default empty: `importlib` is the norm,
`subprocess` is the explicit exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class AdapterCapability:
    """Frozen per-harness capability record consumed by the runner."""

    family: str
    events: frozenset[str]
    payload_parser: Callable[..., dict[str, Any]]
    decision_renderer: Callable[..., tuple[str, int]]
    apply_patch_chain_omissions: frozenset[str] = field(default_factory=frozenset)
    pretool_omissions: frozenset[str] = field(default_factory=frozenset)
    subprocess_modules: frozenset[str] = field(default_factory=frozenset)
