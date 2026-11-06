"""Generated-task fixtures always carry their parent's workflow authority."""

from runtime.api.conftest import insert_epic_task as _insert_task, insert_item


def insert_epic_task(conn, *, epic_id, **kwargs):
    if (
        conn.execute("SELECT 1 FROM items WHERE id=%s", (int(epic_id),)).fetchone()
        is None
    ):
        insert_item(conn, id=int(epic_id), workflow_id="epic", status="implementing")
    return _insert_task(conn, epic_id=epic_id, **kwargs)
