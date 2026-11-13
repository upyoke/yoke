"""Project registration and updates preserve retired projects unchanged."""

import pytest

from yoke_core.domain.projects_upsert import cmd_upsert


@pytest.mark.parametrize("mode", ["create", "update"])
@pytest.mark.parametrize("by_id", [False, True])
def test_retired_project_upsert_refuses_without_writes(test_db, mode, by_id):
    conn = test_db
    project_id = 310
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at, retired_at) "
        "VALUES (%s, 'retired-fixture', 'Original', 'RET', "
        "'2026-01-01', '2026-01-02')",
        (project_id,),
    )
    conn.commit()
    before = dict(
        conn.execute("SELECT * FROM projects WHERE id=%s", (project_id,)).fetchone()
    )
    capabilities_before = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM project_capabilities WHERE project_id=%s ORDER BY id",
            (project_id,),
        ).fetchall()
    ]

    with pytest.raises(ValueError, match="is retired") as error:
        cmd_upsert(
            slug="retired-fixture",
            name="Changed",
            project_id=project_id if by_id else None,
            public_item_prefix="NEW",
            mode=mode,
        )

    assert f"yoke projects unretire --project {project_id}" in str(error.value)
    assert (
        dict(
            conn.execute("SELECT * FROM projects WHERE id=%s", (project_id,)).fetchone()
        )
        == before
    )
    assert [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM project_capabilities WHERE project_id=%s ORDER BY id",
            (project_id,),
        ).fetchall()
    ] == capabilities_before
