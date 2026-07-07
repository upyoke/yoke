"""/ AC-19 stale-term scope tests.

The stale-term regression intentionally scopes to authored agent content
(canonical Bash-capable bodies + rendered Claude/Codex adapters) and
excludes production code that operates on historical QA rows. These
sibling tests pair with the canonical/Claude scans in
``test_agents_render_context.py`` and stay separate so that file does
not press the file-line cap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.agents_render import CANONICAL_DIR
from runtime.api.domain.test_agents_render_workspace_fixtures import (
    resolve_live_repo_root,
)


_BASH_CAPABLE = ("architect", "engineer", "tester", "simulator", "boss")


@pytest.fixture
def repo_root() -> Path:
    """Workspace-anchored live Yoke checkout root for stale-term scans."""
    return resolve_live_repo_root()


def test_rendered_codex_adapters_have_no_stale_terms(repo_root: Path) -> None:
    """AC-18: rendered Codex .toml adapters must not contain the stale
    schema/API names listed in seed.STALE_TERMS. Pairs with the existing
    Claude-side scan in ``test_agents_render_context.py``."""

    codex_dir = repo_root / "runtime/harness/codex/agents"
    for role in _BASH_CAPABLE:
        path = codex_dir / f"yoke-{role}.toml"
        text = path.read_text(encoding="utf-8")
        for stale in seed.STALE_TERMS:
            assert stale not in text, (
                f"yoke-{role}.toml contains stale term {stale!r}"
            )


def test_stale_term_scan_excludes_qa_schema_migration_counters(
    repo_root: Path,
) -> None:
    """AC-19: the stale-term regression intentionally scopes to authored
    agent content, not production code that operates on historical QA
    rows. ``yoke_core.domain.qa_schema`` legitimately contains
    ``qa_kind='review'`` SQL for migration-counter / observation
    queries. Verify those occurrences exist (proving the scope is
    deliberate) and that the canonical scan path used by the
    canonical / rendered stale-term tests never points at this file."""

    qa_kind_review = "qa_kind=" "'review'"
    from yoke_core.domain import qa_schema

    qa_schema_path = Path(qa_schema.__file__).resolve()
    qa_schema_text = qa_schema_path.read_text(encoding="utf-8")
    assert qa_kind_review in qa_schema_text, (
        "qa_schema.py expected to contain legitimate qa_kind='review' "
        "migration-counter SQL — if the term is gone, this test is "
        "obsolete and should be deleted along with the AC-19 carve-out"
    )

    for role in _BASH_CAPABLE:
        canonical = repo_root / CANONICAL_DIR / f"{role}.md"
        assert canonical.resolve() != qa_schema_path.resolve()
