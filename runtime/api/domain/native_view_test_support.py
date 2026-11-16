"""Seed the tracked sources a source checkout's native harness views link to."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.project_contract.source_native_views import NATIVE_AGENT_LINKS


def seed_native_view_sources(root: Path) -> None:
    """Write a minimal rendered tree for every entry in ``NATIVE_AGENT_LINKS``."""
    for _native, source in NATIVE_AGENT_LINKS:
        path = root / source
        if path.suffix == ".json":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"hooks": {}}\n', encoding="utf-8")
        else:
            path.mkdir(parents=True, exist_ok=True)
            (path / "entry.md").write_text("# rendered\n", encoding="utf-8")
