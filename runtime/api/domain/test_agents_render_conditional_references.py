"""A conditional agent reference is named by its prompt, never embedded.

Embedding them is what made every rendered subagent body carry procedures
most dispatches never needed: the regression procedure applies when the
criteria mention regressions, the hard-constraints list when a plan is
actually being written, yet both rode every dispatch. Each conditional
reference is now materialized beside the adapter and named by the body that
needs it, so the dispatch pays for a pointer instead of the procedure.

Sibling of ``test_agents_render_substrate.py``, which is at the authored-file
line cap.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain.agents_render_codex import render_codex_agent_body
from yoke_core.domain.agents_render_subagent_hooks import CANONICAL_DIR


@pytest.fixture
def repo_root() -> Path:
    from runtime.api.domain.test_agents_render_workspace_fixtures import (
        resolve_live_repo_root,
    )

    return resolve_live_repo_root()


def test_conditional_references_are_named_not_embedded(repo_root: Path) -> None:
    """A conditional reference costs a pointer, not the dispatch's context.

    Embedding them is what made every rendered subagent body carry procedures
    most dispatches never needed. Each one is materialized beside the adapter
    and named by the body that needs it.
    """
    from yoke_core.domain.agents_render_references import (
        conditional_reference_paths,
        reference_output_path,
    )

    canonical = repo_root / CANONICAL_DIR
    conditional = conditional_reference_paths(canonical)
    assert conditional, "expected materialized references"
    for frag in conditional:
        assert (repo_root / reference_output_path(frag, canonical)).is_file(), (
            f"{frag.name} is named by a prompt but never materialized"
        )
    for role in ("architect", "tester", "engineer"):
        with patch(
            "yoke_core.domain.schema_api_context._try_live_schema", return_value=None
        ):
            body = render_codex_agent_body(canonical, role)
        for frag in conditional:
            if frag.parent.name != role:
                continue
            text = frag.read_text(encoding="utf-8")
            longest = max(text.splitlines(), key=len, default="")
            assert longest not in body, (
                f"{role}: conditional reference {frag.name} is embedded"
            )
            assert frag.name in body, (
                f"{role}: conditional reference {frag.name} is not named"
            )
