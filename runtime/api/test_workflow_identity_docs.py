"""Documentation regressions for workflow and item identity authority."""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "docs" / "state-management.md"
OVERVIEW = REPO / "docs" / "OVERVIEW.md"
EVENT_CONTRACT = REPO / "docs" / "event-contract.md"
HARNESS_BOOTSTRAP = REPO / "docs" / "harness-bootstrap.md"
HARNESS_ADAPTER_TEMPLATE = REPO / "docs" / "harness-adapter-template.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_state_management_teaches_pin_selected_workflow_authority() -> None:
    text = _read(STATE)
    assert "pinned immutable" in text
    assert "Do not infer a lifecycle or an item type from the workflow id" in text
    assert "`policies.delivery=release_stage`" in text
    assert "`continuous_slice_actions` or `after_merge_action`" in text
    assert "There is no global backlog-item progression" in text
    assert "Dash or Blitz closes directly" not in text
    assert "Issue or Epic closes through Usher delivery" not in text


def test_state_management_uses_current_item_identity_fields() -> None:
    text = _read(STATE)
    for field in (
        "`items.id`",
        "`project_id`",
        "`project_sequence`",
        "`public_item_prefix`",
        "`created_at`",
        "`updated_at`",
    ):
        assert field in text
    for stale in (
        "- `id` — stable `YOK-N` identifier",
        "- `epic` — slug of linked epic directory",
        "- `created` — ISO timestamp",
        "- `updated` — ISO timestamp",
    ):
        assert stale not in text


def test_state_management_teaches_workflow_labels() -> None:
    text = _read(STATE)
    assert "`workflow:<workflow_id>`" in text
    assert "Labels: `type:{epic|issue}`" not in text


def test_overview_names_every_builtin_workflow_and_pinned_authority() -> None:
    text = _read(OVERVIEW)
    assert "Every item — Dash, Blitz, Task, Issue, Epic" in text
    assert "pinned immutable workflow" in text
    assert "Dash runs `idea`" in text
    assert "Blitz adds idea refinement" in text
    assert "Task is the floor subset" in text


def test_overview_uses_project_id_as_item_authority() -> None:
    text = _read(OVERVIEW)
    assert "`items.project_id`" in text
    assert "`projects.slug` is a resolved display" in text
    assert "Items reference projects via their project column" not in text


def test_epic_execution_docs_use_universal_worktree_lanes() -> None:
    state = _read(STATE)
    overview = _read(OVERVIEW)
    event_contract = _read(EVENT_CONTRACT)

    assert "`item_worktree_id`" in state
    assert "`item_worktree_id`" in overview
    assert "`epic_dispatch_chains.item_worktree_id`" in event_contract
    assert "`item_worktrees.item_id`" in event_contract
    assert "`worktree_path`" not in event_contract
    assert "whose `worktree` column matches" not in event_contract
    assert "| `worktree` | TEXT | Branch/worktree name |" not in state
    assert "| `worktree_path` | TEXT | Absolute filesystem path |" not in state


def test_harness_docs_resolve_claude_code_to_claude_manifest() -> None:
    for path in (HARNESS_BOOTSTRAP, HARNESS_ADAPTER_TEMPLATE):
        text = _read(path)
        assert "`claude-vscode` -> `runtime/harness/claude/manifest.json`" in text
        assert "runtime/harness/claude-code/manifest.json" not in text
    assert "Both Yoke-owned executor families ship manifests today" in _read(
        HARNESS_ADAPTER_TEMPLATE
    )
