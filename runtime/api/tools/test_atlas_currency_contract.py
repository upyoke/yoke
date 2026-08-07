"""Always-run floor: ``docs/atlas.md`` must match a fresh Atlas render.

Keeps Atlas currency on the impacted-selection contract floor so a lane
that bypasses hooks still fails locally instead of only in CI. Field-note
collection is stubbed — that section is normalised out of staleness.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import atlas_integrity_audit as audit_mod
from yoke_core.tools import atlas_render_docs as ard


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "docs" / "atlas.md").is_file():
            return parent
    raise RuntimeError("could not locate repo root with docs/atlas.md")


def test_live_repo_atlas_is_current(monkeypatch) -> None:
    monkeypatch.setattr(
        audit_mod,
        "collect_field_notes",
        lambda: {
            "count": 0,
            "rows": [],
            "read_surface_status": "agent_facing",
        },
    )
    root = _repo_root()
    report = audit_mod.build_report(root)
    body = ard.render(report)
    assert not ard.is_stale(root, body=body), (
        "docs/atlas.md is stale relative to a fresh audit render — "
        "run `python3 -m yoke_core.tools.atlas_render_docs render` "
        "or let the pre-commit gate refresh it"
    )
