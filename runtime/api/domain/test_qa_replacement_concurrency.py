"""Concurrent corrections preserve an acyclic obligation graph."""

from yoke_core.domain.qa_requirement_replacement import QaReplacementError


def test_concurrent_disjoint_edges_cannot_close_a_longer_cycle(test_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
    from runtime.api.fixtures.pg_testdb import connect_test_database
    from yoke_core.domain.qa_requirement_replacement import point_at_replacement

    ids = [insert_qa_requirement(test_db, item_id=1)["id"] for _ in range(4)]
    point_at_replacement(test_db, ids[0], ids[1])
    point_at_replacement(test_db, ids[2], ids[3])
    test_db.commit()
    ready = Barrier(2)
    connections = [connect_test_database(test_db.info.dbname) for _ in range(2)]

    def declare_edge(index):
        source, target = ((ids[1], ids[2]), (ids[3], ids[0]))[index]
        ready.wait(timeout=30)
        try:
            point_at_replacement(connections[index], source, target)
            connections[index].commit()
            return "declared"
        except QaReplacementError as exc:
            connections[index].rollback()
            assert "cycle" in str(exc)
            return "refused"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(declare_edge, index) for index in range(2)]
            assert sorted(future.result(timeout=35) for future in futures) == [
                "declared",
                "refused",
            ]
        rows = test_db.execute(
            "SELECT id,replacement_requirement_id FROM qa_requirements WHERE id=ANY(%s)",
            (ids,),
        ).fetchall()
        edges = {row[0]: row[1] for row in rows}
        for origin in ids:
            seen, cursor = set(), origin
            while cursor is not None:
                assert cursor not in seen
                seen.add(cursor)
                cursor = edges.get(cursor)
    finally:
        for connection in connections:
            connection.close()
