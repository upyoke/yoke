# ruff: noqa: F811
"""Generated inventory outputs resolve to their canonical seed sources."""

from runtime.api.domain.test_path_context import (
    fresh_db,  # noqa: F401 - pytest fixture
    _seed_target,
    record_render_relationships,
    read_render_source_for,
    ATLAS_RELPATH,
    EVENT_CATALOG_RELPATH,
    PACKAGED_INSTALL_BUNDLE_TREE_REL,
)


def test_generated_docs_and_bundle_mirror_resolve_seed_sources(fresh_db):
    prefix = f"{PACKAGED_INSTALL_BUNDLE_TREE_REL}/"
    source_path = ".agents/skills/yoke/SKILL.md"
    bundle_target = f"{prefix}{source_path}"
    targets = [ATLAS_RELPATH, EVENT_CATALOG_RELPATH, bundle_target]
    target_ids = {path: _seed_target(fresh_db, path_string=path) for path in targets}
    _seed_target(fresh_db, path_string=source_path)
    fresh_db.commit()

    assert record_render_relationships(fresh_db, project_id=1) == len(targets)
    for target_path in targets:
        sources = read_render_source_for(
            fresh_db,
            target_id=target_ids[target_path],
        )
        assert sources, target_path
    assert read_render_source_for(
        fresh_db,
        target_id=target_ids[bundle_target],
    ) == [source_path]
