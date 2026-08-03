"""Render canonical-agent reference material into portable prompt surfaces.

Canonical agent bodies may refer to source fragments under
``runtime/agents``.  Installed projects do not carry that source tree, so
rendered adapters either embed an always-needed fragment or point at its
materialized file under ``.claude/agents/references``.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.domain.agents_render_conditional import (
    CLAUDE_HARNESS_ID,
    apply_conditional_blocks,
)
from yoke_core.domain.agents_render_context import expand_markers
from yoke_core.domain.agents_render_field_note import (
    expand_field_note_markers,
)


CLAUDE_REFERENCE_DIR = (
    Path("runtime") / "harness" / "claude" / "agents" / "references"
)
INSTALLED_REFERENCE_DIR = Path(".claude") / "agents" / "references"

# These references are needed on every relevant run, so embedding them keeps
# the adapter self-contained. Other fragments are materialized on demand.
INLINE_REFERENCE_PATHS = frozenset(
    {
        Path("architect") / "hard-constraints.md",
        Path("tester") / "regression-detection.md",
    }
)
_SHARED_REFERENCE_PATHS = (
    Path("_shared") / "ouroboros-reflection-contract.md",
)
_CANONICAL_REFERENCE_RE = re.compile(
    r"runtime/agents/(?P<relative>[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.md)"
)


def _role_fragment_paths(canonical_dir: Path) -> tuple[Path, ...]:
    """Return one-level role fragments in deterministic order."""
    return tuple(
        path
        for directory in sorted(canonical_dir.iterdir())
        if directory.is_dir() and not directory.name.startswith("_")
        for path in sorted(directory.glob("*.md"))
    )


def inline_fragment_paths(canonical_dir: Path, role: str) -> tuple[Path, ...]:
    """Return the canonical fragments that belong in *role*'s prompt."""
    return tuple(
        path
        for path in _role_fragment_paths(canonical_dir)
        if path.parent.name == role
        and path.relative_to(canonical_dir) in INLINE_REFERENCE_PATHS
    )


def conditional_reference_paths(canonical_dir: Path) -> tuple[Path, ...]:
    """Return source fragments that are materialized beside installed agents."""
    fragments = [
        path
        for path in _role_fragment_paths(canonical_dir)
        if path.relative_to(canonical_dir) not in INLINE_REFERENCE_PATHS
    ]
    fragments.extend(
        canonical_dir / relative
        for relative in _SHARED_REFERENCE_PATHS
        if (canonical_dir / relative).is_file()
    )
    return tuple(sorted(fragments))


def reference_output_path(source_path: Path, canonical_dir: Path) -> Path:
    """Return the rendered Claude reference path for one canonical source."""
    return CLAUDE_REFERENCE_DIR / source_path.relative_to(canonical_dir)


def installed_reference_path(relative_path: Path) -> Path:
    """Return the project-relative path an installed agent can read."""
    return INSTALLED_REFERENCE_DIR / relative_path


def translate_canonical_reference_paths(text: str, canonical_dir: Path) -> str:
    """Replace materialized canonical reference paths with installed paths.

    Inline references intentionally remain absent from their parent prompt's
    prose; an unconverted inline path is caught by the rendered-adapter test.
    """
    materialized = {
        path.relative_to(canonical_dir).as_posix()
        for path in conditional_reference_paths(canonical_dir)
    }

    def replace(match: re.Match[str]) -> str:
        relative = match.group("relative")
        if relative not in materialized:
            return match.group(0)
        return installed_reference_path(Path(relative)).as_posix()

    return _CANONICAL_REFERENCE_RE.sub(replace, text)


def render_reference_text(
    text: str,
    *,
    canonical_dir: Path,
    harness_id: str,
) -> str:
    """Expand common renderer markers and translate portable references."""
    expanded = apply_conditional_blocks(
        expand_field_note_markers(expand_markers(text)), harness_id
    )
    return translate_canonical_reference_paths(expanded, canonical_dir)


def render_agent_prompt_body(
    canonical_dir: Path,
    role: str,
    *,
    harness_id: str,
) -> str:
    """Render one agent's canonical body and its unconditional references."""
    parts = [
        render_reference_text(
            (canonical_dir / f"{role}.md").read_text(encoding="utf-8"),
            canonical_dir=canonical_dir,
            harness_id=harness_id,
        ).rstrip("\n")
    ]
    for fragment in inline_fragment_paths(canonical_dir, role):
        parts.append(
            render_reference_text(
                fragment.read_text(encoding="utf-8"),
                canonical_dir=canonical_dir,
                harness_id=harness_id,
            ).rstrip("\n")
        )
    return "\n\n".join(parts) + "\n"


def rendered_reference_outputs(canonical_dir: Path) -> list[tuple[Path, str]]:
    """Return relative output paths and text for on-demand reference files."""
    return [
        (
            reference_output_path(path, canonical_dir),
            render_reference_text(
                path.read_text(encoding="utf-8"),
                canonical_dir=canonical_dir,
                harness_id=CLAUDE_HARNESS_ID,
            ),
        )
        for path in conditional_reference_paths(canonical_dir)
    ]


__all__ = (
    "CLAUDE_REFERENCE_DIR",
    "INLINE_REFERENCE_PATHS",
    "INSTALLED_REFERENCE_DIR",
    "conditional_reference_paths",
    "inline_fragment_paths",
    "installed_reference_path",
    "reference_output_path",
    "render_agent_prompt_body",
    "render_reference_text",
    "rendered_reference_outputs",
    "translate_canonical_reference_paths",
)
