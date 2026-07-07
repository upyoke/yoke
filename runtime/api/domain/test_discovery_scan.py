from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.discovery_scan import run_scan


@pytest.fixture
def seeded_repo(tmp_path):
    with init_test_db(tmp_path) as db_path:
        yield tmp_path, db_path


def _insert_ouroboros(
    conn, *, timestamp: str, agent: str, context: str,
    category: str, body: str,
) -> None:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        """
        INSERT INTO ouroboros_entries
            (timestamp, agent, context, category, body, created_at)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p})
        """.format(p=p),
        (timestamp, agent, context, category, body, iso8601_now()),
    )


def test_basic_file_creation(seeded_repo):
    root, _db_path = seeded_repo
    output: list[str] = []

    class _Writer:
        def write(self, value: str) -> int:
            output.append(value)
            return len(value)

    rc = run_scan("42", repo_root=str(root), stdout=_Writer(), stderr=_Writer())
    assert rc == 0
    text = "".join(output)
    line = [
        part for part in text.splitlines()
        if part.startswith("DISCOVERY_FILE=")
    ][-1]
    discovery_file = Path(line.split("=", 1)[1])
    assert discovery_file.is_file()
    content = discovery_file.read_text()
    assert "UNREVIEWED_OUROBOROS=0" in content
    discovery_file.unlink()


def test_detects_item_scoped_ouroboros(seeded_repo):
    root, db_path = seeded_repo
    conn = connect_test_db(db_path)
    _insert_ouroboros(
        conn, timestamp="2026-03-10T10:00:00Z", agent="engineer",
        context="YOK-9999/task-1", category="problem", body="One",
    )
    _insert_ouroboros(
        conn, timestamp="2026-03-10T11:00:00Z", agent="engineer",
        context="shepherd YOK-9999 refined_idea_to_planning",
        category="idea", body="Two",
    )
    _insert_ouroboros(
        conn, timestamp="2026-03-10T12:00:00Z", agent="engineer",
        context="YOK-43", category="idea", body="Other ticket",
    )
    _insert_ouroboros(
        conn, timestamp="2026-03-10T13:00:00Z", agent="engineer",
        context="demo", category="idea", body="Unscoped",
    )
    conn.commit()
    conn.close()

    output: list[str] = []

    class _Writer:
        def write(self, value: str) -> int:
            output.append(value)
            return len(value)

    rc = run_scan(
        "YOK-9999", repo_root=str(root), stdout=_Writer(), stderr=_Writer()
    )
    assert rc == 0
    line = [
        part for part in "".join(output).splitlines()
        if part.startswith("DISCOVERY_FILE=")
    ][-1]
    discovery_file = Path(line.split("=", 1)[1])
    content = discovery_file.read_text()
    assert "UNREVIEWED_OUROBOROS=2" in content
    assert "YOK-9999/task-1" in content
    assert "shepherd YOK-9999 refined_idea_to_planning" in content
    assert "Other ticket" not in content
    assert "Unscoped" not in content
    discovery_file.unlink()


def test_ouroboros_context_match_allows_bare_item_refs(seeded_repo):
    root, db_path = seeded_repo
    conn = connect_test_db(db_path)
    _insert_ouroboros(
        conn, timestamp="2026-03-10T10:00:00Z", agent="tester",
        context="1245/008", category="idea", body="Bare task context",
    )
    _insert_ouroboros(
        conn, timestamp="2026-03-10T11:00:00Z", agent="tester",
        context="YOK-12450/task-1", category="idea", body="Neighbor",
    )
    conn.commit()
    conn.close()

    output: list[str] = []

    class _Writer:
        def write(self, value: str) -> int:
            output.append(value)
            return len(value)

    rc = run_scan(
        "YOK-1245", repo_root=str(root), stdout=_Writer(), stderr=_Writer()
    )
    assert rc == 0
    line = [
        part for part in "".join(output).splitlines()
        if part.startswith("DISCOVERY_FILE=")
    ][-1]
    discovery_file = Path(line.split("=", 1)[1])
    content = discovery_file.read_text()
    assert "UNREVIEWED_OUROBOROS=1" in content
    assert "Bare task context" in content
    assert "Neighbor" not in content
    discovery_file.unlink()


def test_missing_args_returns_usage(tmp_path):
    output: list[str] = []

    class _Writer:
        def write(self, value: str) -> int:
            output.append(value)
            return len(value)

    rc = run_scan("", repo_root=str(tmp_path), stdout=_Writer(), stderr=_Writer())
    assert rc == 2
    assert "python3 -m yoke_core.domain.discovery_scan" in "".join(output)
