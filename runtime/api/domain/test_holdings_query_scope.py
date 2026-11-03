"""Holdings reads exclude unrelated history and preserve selected owners."""

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.session_holdings import (
    insert_item_claim, insert_session, insert_session_path_claim, instant_ago,
)
from yoke_core.domain.sessions_holdings_claim_rows import all_claim_rows
from yoke_core.domain.sessions_holdings_path_rows import path_rows
from yoke_core.domain.sessions_holdings_projection import session_holdings_by_session


def test_path_rows_scope_history_and_keep_unreleased_claims(test_db):
    for session in ('selected', 'unrelated'):
        insert_session(test_db, session)
        insert_session_path_claim(test_db, session, released_at=instant_ago(5))
    insert_session_path_claim(test_db, 'unrelated')
    rows = path_rows(test_db, claims=[], session_ids=('selected',))
    assert len(rows) == 2
    assert sum(row['owner_session_id'] == 'selected' for row in rows) == 1
    assert sum(row['released_at'] is None for row in rows) == 1
    assert all(row['declared_count'] == 0 for row in rows)
    assert len(path_rows(test_db, claims=[], session_ids=None)) == 3


def test_item_history_and_counts_survive_session_selection(test_db):
    insert_session(test_db, 'selected')
    insert_item(test_db, id=301, title='historical files')
    insert_item_claim(test_db, 'selected', 301, released_at=instant_ago(5))
    actor = test_db.execute('SELECT id FROM actors ORDER BY id LIMIT 1').fetchone()[0]
    claim = test_db.execute(
        "INSERT INTO path_claims (state,mode,owner_kind,owner_item_id,"
        "registered_by_actor_id,integration_target,registered_at,released_at) "
        "VALUES ('released','exclusive','item',301,%s,'main',%s,%s) RETURNING id",
        (actor, instant_ago(10), instant_ago(5)),
    ).fetchone()[0]
    for path in ('one', 'two'):
        target = test_db.execute(
            "INSERT INTO path_targets (project_id,kind,path_string,generation,created_at) "
            "VALUES (1,'file',%s,1,%s) RETURNING id", (path, instant_ago()),
        ).fetchone()[0]
        test_db.execute(
            'INSERT INTO path_claim_targets (claim_id,target_id,declared_at) VALUES (%s,%s,%s)',
            (claim, target, instant_ago()),
        )
    test_db.commit()
    claims = [dict(row) for row in all_claim_rows(test_db, session_ids=['selected'])]
    rows = path_rows(test_db, claims=claims, session_ids=('selected',))
    assert len(rows) == 1
    assert rows[0]['declared_count'] == 2
    holdings = session_holdings_by_session(test_db, session_ids=iter(['selected']))
    assert holdings['selected']['previous'][0]['path_count'] == 2
