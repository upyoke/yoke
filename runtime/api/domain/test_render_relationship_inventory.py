# ruff: noqa: F811
"""Generated inventory outputs resolve to their canonical seed sources."""

from runtime.api.domain.path_context_test_support import (fresh_db as fresh_db)

from runtime.api.domain.path_context_test_support import (
    _seed_target,
    record_render_relationships,
    read_render_source_for,
    ATLAS_RELPATH,
    EVENT_CATALOG_RELPATH,
)


def test_generated_docs_resolve_seed_sources(fresh_db):
    targets = [ATLAS_RELPATH, EVENT_CATALOG_RELPATH]
    target_ids = {path: _seed_target(fresh_db, path_string=path) for path in targets}
    fresh_db.commit()

    assert record_render_relationships(fresh_db, project_id=1) == len(targets)
    for target_path in targets:
        sources = read_render_source_for(
            fresh_db,
            target_id=target_ids[target_path],
        )
        assert sources, target_path
