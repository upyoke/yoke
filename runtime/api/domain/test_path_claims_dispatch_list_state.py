"""Coverage for ``path-claims list --state`` filter parsing.

Regression home for the friction logged repeatedly across YOK-1888 /
1892 / 1895 / 1896 / 1897 / 1898: the documented widen-before-edit
recipe passed ``--state planned,active,blocked`` (one comma-joined
token) which matched no row and silently returned ``[]`` even when an
active claim existed. ``split_states`` now flattens repeatable and
comma-separated forms alike.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import (
    path_claims_dispatch,
    path_claims_dispatch_amend,
    path_claims_dispatch_io,
    path_claims_dispatch_state,
)
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    ambient_holder_session, conn, local_human, seed_target,
    seed_test_holder_for,
)


def _seed_item(conn, *, item_id: int = 9001) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    seed_test_holder_for(conn, item_id=item_id)
    conn.commit()
    return item_id


@pytest.fixture
def patch_conn(monkeypatch, conn, ambient_holder_session):  # noqa: F811
    """Use the in-memory conn for every dispatcher surface; pin ambient holder."""
    class _NoCloseConn:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, *a, **kw):
            return self._inner.execute(*a, **kw)

        def executemany(self, *a, **kw):
            return self._inner.executemany(*a, **kw)

        def commit(self):
            return self._inner.commit()

        def close(self):
            return None

    wrapper = _NoCloseConn(conn)
    monkeypatch.setattr(path_claims_dispatch, "_open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_amend, "open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_state, "open_conn", lambda: wrapper)
    return conn


def _capture(capsys):
    captured = capsys.readouterr()
    return captured.out, captured.err


def _register_planned(conn, capsys) -> int:
    actor = local_human(conn)
    item_id = _seed_item(conn)
    seed_target(conn, path_string="runtime/api/domain")
    path_claims_dispatch.cmd_register(
        [
            "--item", str(item_id),
            "--integration-target", "main",
            "--paths", "runtime/api/domain",
            "--actor-id", str(actor),
        ]
    )
    capsys.readouterr()
    return item_id


class TestListStateFilter:
    def test_comma_separated_state_matches_active_claim(self, patch_conn, capsys):
        # The exact broken recipe form must match the (planned) claim,
        # not return [] by treating "planned,active,blocked" as one state.
        item_id = _register_planned(patch_conn, capsys)

        rc = path_claims_dispatch.cmd_list(
            ["--item", str(item_id), "--state", "planned,active,blocked"]
        )
        out, _ = _capture(capsys)
        assert rc == 0
        claims = json.loads(out.strip())
        assert len(claims) == 1
        assert claims[0]["state"] == "planned"

    def test_comma_and_repeated_forms_are_equivalent(self, patch_conn, capsys):
        item_id = _register_planned(patch_conn, capsys)

        path_claims_dispatch.cmd_list(
            ["--item", str(item_id), "--state", "planned,active"]
        )
        comma_out, _ = _capture(capsys)
        path_claims_dispatch.cmd_list(
            ["--item", str(item_id), "--state", "planned", "--state", "active"]
        )
        repeated_out, _ = _capture(capsys)
        assert json.loads(comma_out.strip()) == json.loads(repeated_out.strip())
        assert len(json.loads(comma_out.strip())) == 1


class TestSplitStates:
    def test_none_and_empty_stay_none(self):
        split = path_claims_dispatch_io.split_states
        assert split(None) is None
        assert split([]) is None
        assert split([""]) is None
        assert split([" , "]) is None

    def test_repeated_flags_pass_through(self):
        assert path_claims_dispatch_io.split_states(["planned", "active"]) == [
            "planned",
            "active",
        ]

    def test_comma_separated_is_split(self):
        assert path_claims_dispatch_io.split_states(
            ["planned,active,blocked"]
        ) == ["planned", "active", "blocked"]

    def test_mixed_and_whitespace(self):
        assert path_claims_dispatch_io.split_states(
            ["planned, active", "blocked"]
        ) == ["planned", "active", "blocked"]
