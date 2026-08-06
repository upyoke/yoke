"""Render harness adapters from canonical Yoke source.

Writes per-harness agents, configs, and manifests under
``runtime/harness/{id}/`` plus repo-root native surfaces (``.codex/agents``,
``.cursor/agents``, and materialized ``.cursor/hooks.json``). Shape-specific
renderers live in sibling modules. Writers require ``target_root``; readers
use a strict resolver; atomic writes enforce work-claim and seed-root
authority.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yoke_core.domain.agents_render_claude import (
    render_claude_manifest_json,
    render_claude_settings_json,
)
from yoke_core.domain.agents_render_codex import (
    render_codex_agent,
    render_codex_hooks_json,
    render_codex_manifest_json,
)
from yoke_core.domain.agents_render_conditional import (
    detect_conditional_marker_drift,
)
from yoke_core.domain.agents_render_cursor import (
    render_cursor_agent,
    render_cursor_hooks_json,
    render_cursor_manifest_json,
)
from yoke_core.domain.agents_render_native_links import (
    ensure_native_agents_link,
    native_agents_link_drift,
)
from yoke_core.domain.agents_render_context import (
    detect_canonical_body_drift,
)
from yoke_core.domain.agents_render_field_note import (
    detect_field_note_marker_drift,
)
from yoke_core.domain.agents_render_references import rendered_reference_outputs
from yoke_core.domain.agents_render_subagent_hooks import (
    CANONICAL_DIR,
    CLAUDE_SPEC_KEY_ORDER,  # noqa: F401 - preserve the renderer's public exports
    is_bash_capable_subagent,  # noqa: F401 - preserve the renderer's public exports
    load_canonical,  # noqa: F401 - preserve the renderer's public exports
    load_claude_spec,  # noqa: F401 - preserve the renderer's public exports
    render_claude_agent,
    render_claude_subagent_hooks_block,  # noqa: F401 - preserve the renderer's public exports
)
from yoke_core.domain.agents_render_workspace import (
    require_reader_root,
    resolve_target_root_for_cli,  # noqa: F401 - preserve the renderer's public exports
    _repo_root,  # noqa: F401 - re-exported for CLI/legacy consumers; reader hot path uses require_reader_root
)
from yoke_core.domain.workspace_authority import (
    assert_seed_source_under_target_root,
    assert_target_under_session_work_authority,
)
from yoke_core.domain import agents_render_project_install


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAUDE_OUT_DIR = Path("runtime") / "harness" / "claude" / "agents"
CODEX_OUT_DIR = Path("runtime") / "harness" / "codex" / "agents"
CODEX_NATIVE_AGENTS_DIR = Path(".codex/agents")
CURSOR_OUT_DIR = Path("runtime") / "harness" / "cursor" / "agents"
CURSOR_NATIVE_AGENTS_DIR = Path(".cursor/agents")

CLAUDE_SETTINGS_PATH = Path("runtime") / "harness" / "claude" / "settings.json"
CLAUDE_NATIVE_SETTINGS_PATH = Path(".claude") / "settings.json"
CLAUDE_MANIFEST_PATH = Path("runtime") / "harness" / "claude" / "manifest.json"
CODEX_HOOKS_PATH = Path("runtime") / "harness" / "codex" / "hooks.json"
CODEX_MANIFEST_PATH = Path("runtime") / "harness" / "codex" / "manifest.json"
CURSOR_HOOKS_PATH = Path("runtime") / "harness" / "cursor" / "hooks.json"
CURSOR_MANIFEST_PATH = Path("runtime") / "harness" / "cursor" / "manifest.json"
CURSOR_NATIVE_HOOKS_PATH = Path(".cursor") / "hooks.json"

# The seven primary Yoke agents.
AGENTS = [
    "product-manager",
    "product-designer",
    "architect",
    "engineer",
    "tester",
    "simulator",
    "boss",
]

# Roles whose rendered adapters embed an always-needed reference section.
ROLES_WITH_INLINE_REFERENCES = {"architect", "tester"}


def _resolve_reader_root(target_root: Optional[Path]) -> Path:
    """Resolve ``target_root`` for reader helpers — see ``require_reader_root``."""
    return require_reader_root(target_root)


# ---------------------------------------------------------------------------
# Claude agent (.md) writer helpers
# ---------------------------------------------------------------------------


def write_all_claude(*, target_root: Path, dry_run: bool = False) -> dict[str, tuple[str, str]]:
    """Render Claude agents and on-demand references for an explicit checkout."""
    results: dict[str, tuple[str, str]] = {}
    root = Path(target_root)
    outputs = [
        (CLAUDE_OUT_DIR / f"yoke-{agent}.md", render_claude_agent(agent, target_root=root))
        for agent in AGENTS
    ]
    outputs.extend(rendered_reference_outputs(root / CANONICAL_DIR))
    for rel_path, rendered in outputs:
        out_path = root / rel_path
        rel = str(rel_path)
        if dry_run:
            existing = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
            action = "would-write" if rendered != existing else "skip"
            results[rel] = (action, rendered)
            continue
        _atomic_write(out_path, rendered, target_root=root)
        results[rel] = ("write", rendered)
    return results


def detect_drift(*, target_root: Optional[Path] = None) -> list[str]:
    """Compare rendered Claude agents to on-disk files (Claude-only legacy surface).

    Used by the existing ``HC-agent-canonical-drift`` doctor check. The
    broader substrate drift surface lives in :func:`detect_substrate_drift`.
    """
    root = _resolve_reader_root(target_root)
    drift: list[str] = []
    for agent in AGENTS:
        out_path = root / CLAUDE_OUT_DIR / f"yoke-{agent}.md"
        rendered = render_claude_agent(agent, target_root=root)
        if not out_path.exists():
            drift.append(f"missing: {CLAUDE_OUT_DIR}/yoke-{agent}.md")
            continue
        if out_path.read_text(encoding="utf-8") != rendered:
            drift.append(f"drift: {CLAUDE_OUT_DIR}/yoke-{agent}.md")
    return drift


# ---------------------------------------------------------------------------
# Universal substrate rendering — every output set in one place
# ---------------------------------------------------------------------------


def _atomic_write(out_path: Path, rendered: str, *, target_root: Path) -> None:
    assert_target_under_session_work_authority(out_path)
    _assert_seed_under_target_root(target_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(rendered, encoding="utf-8")
    os.replace(str(tmp_path), str(out_path))


def _assert_seed_under_target_root(target_root: Path) -> None:
    """Defense for Coupling B: seed loaded from a different tree than target_root.

    The renderer's per-output context expander imports
    ``schema_api_context_seed`` at module load. When cwd != target_root,
    the seed loaded from cwd's tree drives renders written into
    target_root — silent wrong-tree content. The check fires at write
    time; module import has already happened.
    """
    from yoke_core.domain import schema_api_context_seed as _seed
    assert_seed_source_under_target_root(
        getattr(_seed, "__file__", None),
        target_root,
        seed_module_name="schema_api_context_seed",
    )


def _enumerate_outputs(target_root: Optional[Path] = None) -> list[tuple[Path, str]]:
    """Return every (relative_path, rendered_content) tuple in render order."""
    root = _resolve_reader_root(target_root)
    outputs: list[tuple[Path, str]] = []
    for agent in AGENTS:
        outputs.append(
            (CLAUDE_OUT_DIR / f"yoke-{agent}.md", render_claude_agent(agent, target_root=root))
        )
    outputs.extend(rendered_reference_outputs(root / CANONICAL_DIR))
    outputs.append((CLAUDE_SETTINGS_PATH, render_claude_settings_json()))
    outputs.append((CLAUDE_NATIVE_SETTINGS_PATH, render_claude_settings_json()))
    outputs.append((CLAUDE_MANIFEST_PATH, render_claude_manifest_json()))
    for agent in AGENTS:
        outputs.append(
            (
                CODEX_OUT_DIR / f"yoke-{agent}.toml",
                render_codex_agent(root / CANONICAL_DIR, agent),
            )
        )
    outputs.append((CODEX_HOOKS_PATH, render_codex_hooks_json()))
    outputs.append((CODEX_MANIFEST_PATH, render_codex_manifest_json()))
    for agent in AGENTS:
        outputs.append(
            (
                CURSOR_OUT_DIR / f"yoke-{agent}.md",
                render_cursor_agent(root / CANONICAL_DIR, agent),
            )
        )
    outputs.append((CURSOR_HOOKS_PATH, render_cursor_hooks_json()))
    outputs.append((CURSOR_MANIFEST_PATH, render_cursor_manifest_json()))
    outputs.append((CURSOR_NATIVE_HOOKS_PATH, render_cursor_hooks_json()))
    return outputs


def write_all(*, target_root: Path, dry_run: bool = False) -> dict[str, tuple[str, str]]:
    """Render every substrate output. Returns ``{relpath: (action, rendered)}``.

    ``target_root`` is required and keyword-only — there is no implicit cwd
    fallback inside the writer hot path. Pass an explicit checkout root.
    """
    results: dict[str, tuple[str, str]] = {}
    root = Path(target_root)
    project_results = agents_render_project_install.write_if_applicable(target_root=root, dry_run=dry_run)
    if project_results is not None:
        return project_results
    for rel_path, rendered in _enumerate_outputs(root):
        out_path = root / rel_path
        rel = str(rel_path)
        if dry_run:
            existing = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
            action = "would-write" if rendered != existing else "skip"
            results[rel] = (action, rendered)
            continue
        existing = out_path.read_text(encoding="utf-8") if out_path.exists() else None
        if existing == rendered:
            results[rel] = ("skip", rendered)
            continue
        _atomic_write(out_path, rendered, target_root=root)
        results[rel] = ("write", rendered)
    for native_dir, out_dir in _NATIVE_AGENT_LINKS:
        link_action, link_target = ensure_native_agents_link(
            root, out_dir, native_dir, dry_run=dry_run
        )
        results[str(native_dir)] = (link_action, link_target)
    return results


# Harnesses that consume rendered adapters through a repo-root symlink.
_NATIVE_AGENT_LINKS: tuple[tuple[Path, Path], ...] = (
    (CODEX_NATIVE_AGENTS_DIR, CODEX_OUT_DIR),
    (CURSOR_NATIVE_AGENTS_DIR, CURSOR_OUT_DIR),
)


def detect_substrate_drift(*, target_root: Optional[Path] = None) -> list[str]:
    """Compare every rendered substrate output to on-disk content.

    Returns a list of human-readable drift descriptions. Empty list means
    the on-disk substrate matches the rendered universal source. Consumed
    by the lane R / task 10 health check ``HC-harness-substrate-drift``.
    """
    root = _resolve_reader_root(target_root)
    project_drift = agents_render_project_install.drift_if_applicable(target_root=root)
    if project_drift is not None:
        return project_drift
    drift: list[str] = []
    for agent in AGENTS:
        canonical_path = root / CANONICAL_DIR / f"{agent}.md"
        if not canonical_path.exists():
            continue
        canonical_text = canonical_path.read_text(encoding="utf-8")
        drift.extend(
            detect_canonical_body_drift(
                canonical_text, f"{CANONICAL_DIR}/{agent}.md"
            )
        )
        drift.extend(
            detect_conditional_marker_drift(
                canonical_text, f"{CANONICAL_DIR}/{agent}.md"
            )
        )
        drift.extend(
            detect_field_note_marker_drift(
                canonical_text, f"{CANONICAL_DIR}/{agent}.md"
            )
        )
    try:
        outputs = _enumerate_outputs(root)
    except Exception as exc:
        drift.append(f"render-error: {exc}")
        outputs = []
    for rel_path, rendered in outputs:
        out_path = root / rel_path
        if rel_path in {CLAUDE_NATIVE_SETTINGS_PATH, CURSOR_NATIVE_HOOKS_PATH} and out_path.is_symlink():
            drift.append(f"invalid symlink: {rel_path}")
            continue
        if not out_path.exists():
            drift.append(f"missing: {rel_path}")
            continue
        if out_path.read_text(encoding="utf-8") != rendered:
            drift.append(f"drift: {rel_path}")
    for native_dir, out_dir in _NATIVE_AGENT_LINKS:
        drift.extend(native_agents_link_drift(root, out_dir, native_dir))
    return drift


# CLI lives in agents_render_workspace.run_cli — keeps the writer hot path
# free of argparse plumbing and stays under the 350-line cap.

def write_all_and_record(
    *, target_root: Path, dry_run: bool = False,
) -> dict[str, tuple[str, str]]:
    """Render, then idempotently register render relationships in the DB.

    Wraps :func:`write_all` so the canonical CLI surface and the
    ``agents.render.run`` function-call handler share one post-render
    registration step. File writes remain client-local while relationship
    registration follows the active control-plane transport. Registration is
    opportunistic — when the authority or the ``path_targets`` rows are
    unavailable, the helper returns ``0`` and the renderer flow continues. Dry-runs
    skip registration so a check-only invocation never mutates
    ``path_context_values``.

    A non-dry-run write also re-syncs the packaged install-bundle
    snapshot: the render rewrites several of its source dirs (Claude
    agents, Codex agents, Claude rules), so chaining the idempotent
    :func:`install_bundle_tree_sync.sync` here keeps the wheel-packaged
    copy byte-identical instead of drifting until the next manual sync.
    """
    results = write_all(target_root=target_root, dry_run=dry_run)
    if not dry_run:
        from yoke_core.domain.agents_render_path_context import (
            record_render_relationships_to_canonical_db,
        )
        record_render_relationships_to_canonical_db()
        from yoke_core.domain.install_bundle_tree_sync import (
            sync as sync_install_bundle_tree,
        )
        sync_install_bundle_tree(target_root=target_root)
    return results


if __name__ == "__main__":
    from yoke_core.domain.agents_render_workspace import run_cli

    run_cli(
        write_all=write_all_and_record,
        detect_substrate_drift=detect_substrate_drift,
    )
