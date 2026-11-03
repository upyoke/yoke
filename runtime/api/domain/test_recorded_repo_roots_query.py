"""Recorded lane roots stay complete without returning every lane."""

from runtime.api.fixtures.backlog import insert_item, insert_item_worktree
from yoke_core.domain.lint_session_cwd_path_authority import recorded_repo_roots


def test_distinct_roots_include_released_and_nested_lanes(test_db):
    paths = [
        '/repo/.worktrees/one',
        '/repo/.worktrees/two',
        '/other/.worktrees/released',
        '/repo/.worktrees/nested/.worktrees/inner',
        '/plain/checkout',
        '/.worktrees/root-lane',
    ]
    for number, path in enumerate(paths, 300):
        insert_item(test_db, id=number, title='recorded lane')
        lane = insert_item_worktree(test_db, item_id=number, branch=f'lane-{number}')
        test_db.execute(
            "UPDATE item_worktrees SET path=%s,state='released' WHERE id=%s",
            (path, lane['id']),
        )
    test_db.commit()
    assert recorded_repo_roots(test_db) == [
        '/', '/other', '/repo', '/repo/.worktrees/nested',
    ]
