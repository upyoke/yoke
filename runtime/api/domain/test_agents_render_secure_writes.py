"""Secure atomic-write regressions for native harness config rendering."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.domain.test_agents_render_substrate import (
    _seed_minimal_canonical_tree,
)
from yoke_core.domain.agents_render import (
    CLAUDE_NATIVE_SETTINGS_PATH,
    CLAUDE_SETTINGS_PATH,
    CURSOR_HOOKS_PATH,
    CURSOR_NATIVE_HOOKS_PATH,
    write_all,
)


@pytest.fixture
def rendered_repo(tmp_path: Path):
    _seed_minimal_canonical_tree(tmp_path)
    with patch("yoke_core.domain.agents_render.AGENTS", ["architect"]):
        write_all(target_root=tmp_path)
        yield tmp_path


@pytest.mark.parametrize(
    ("native_rel", "canonical_rel"),
    [
        (CLAUDE_NATIVE_SETTINGS_PATH, CLAUDE_SETTINGS_PATH),
        (CURSOR_NATIVE_HOOKS_PATH, CURSOR_HOOKS_PATH),
    ],
)
def test_render_materializes_byte_equal_scanned_config_symlink(
    rendered_repo: Path,
    native_rel: Path,
    canonical_rel: Path,
) -> None:
    native = rendered_repo / native_rel
    canonical = rendered_repo / canonical_rel
    native.unlink()
    native.symlink_to(canonical)
    assert native.read_bytes() == canonical.read_bytes()

    preview = write_all(target_root=rendered_repo, dry_run=True)
    result = write_all(target_root=rendered_repo)

    assert preview[str(native_rel)][0] == "would-write"
    assert result[str(native_rel)][0] == "write"
    assert native.is_file() and not native.is_symlink()
    assert native.read_bytes() == canonical.read_bytes()


def test_render_does_not_follow_predictable_temp_symlink(
    rendered_repo: Path,
) -> None:
    victim = rendered_repo.parent / "outside-settings.json"
    victim.write_text("operator data\n", encoding="utf-8")
    target = rendered_repo / CLAUDE_NATIVE_SETTINGS_PATH
    target.write_text("drift\n", encoding="utf-8")
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.symlink_to(victim)

    write_all(target_root=rendered_repo)

    assert victim.read_text(encoding="utf-8") == "operator data\n"
    assert temporary.is_symlink()
    assert target.read_bytes() == (
        rendered_repo / CLAUDE_SETTINGS_PATH
    ).read_bytes()


@pytest.mark.parametrize("parent_rel", [Path(".claude"), Path(".cursor")])
def test_render_refuses_symlinked_scanned_config_parent(
    rendered_repo: Path,
    parent_rel: Path,
) -> None:
    parent = rendered_repo / parent_rel
    real_parent = rendered_repo / f"{parent_rel.name}-real"
    parent.rename(real_parent)
    parent.symlink_to(real_parent.name, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symlinked parent"):
        write_all(target_root=rendered_repo)
