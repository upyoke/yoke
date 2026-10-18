"""Project scope uses bound parameters."""

import pytest

from yoke_contracts.board.data import BoardDataError
from yoke_contracts.board.project_scope import (
    project_filter,
    project_ref_where,
    scope_project_id,
    scoped_project_visibility,
)
from yoke_core.board.db import BoardDB


def test_project_scope_changes_parameters_not_query_shape():
    first_sql, first_params = project_filter("yoke", "i")
    second_sql, second_params = project_filter("externalwebapp", "i")

    assert first_sql == second_sql
    assert first_params == ("yoke",)
    assert second_params == ("externalwebapp",)
    assert "yoke" not in first_sql
    assert "externalwebapp" not in second_sql


@pytest.mark.parametrize("visibility", [None, (), ("yoke",), ("externalwebapp",)])
@pytest.mark.parametrize("numeric", [True, False])
def test_explicit_sql_scope_intersects_visibility(populated_db, visibility, numeric):
    with BoardDB(populated_db) as db:
        ids = dict(db.query("SELECT slug,id FROM projects"))
        project_id = ids["yoke"]
        visible = None if visibility is None else tuple(ids[s] for s in visibility)
        scope = str(project_id) if numeric else "yoke"
        expected = {project_id} if visible is None or project_id in visible else set()
        with scoped_project_visibility(visible):
            clause, params = project_filter(scope, "i")
            items = db.query(
                "SELECT DISTINCT i.project_id FROM items i WHERE 1=1" + clause,
                params,
            )
            where, params = project_ref_where(scope)
            projects = db.query("SELECT id FROM projects WHERE " + where, params)
        assert {row[0] for row in items} == expected
        assert {row[0] for row in projects} == expected


@pytest.mark.parametrize("visibility", [None, (), ("yoke",), ("externalwebapp",)])
@pytest.mark.parametrize("kind", ["integer", "numeric", "slug"])
def test_explicit_resolution_respects_visibility(populated_db, visibility, kind):
    with BoardDB(populated_db) as db:
        ids = dict(db.query("SELECT slug,id FROM projects"))
        project_id = ids["yoke"]
        scope = {"integer": project_id, "numeric": str(project_id), "slug": "yoke"}[
            kind
        ]
        visible = None if visibility is None else tuple(ids[s] for s in visibility)
        with scoped_project_visibility(visible):
            if visible is None or project_id in visible:
                assert scope_project_id(db, scope) == project_id
            else:
                with pytest.raises(BoardDataError) as denied:
                    scope_project_id(db, scope)
                assert str(denied.value) == (
                    "project scope is unavailable; choose a readable project or all"
                )


def test_local_missing_slug_retains_lookup_refusal(populated_db):
    with BoardDB(populated_db) as db, scoped_project_visibility(None):
        with pytest.raises(LookupError, match="not found"):
            scope_project_id(db, "missing-project")
