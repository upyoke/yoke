# ruff: noqa: F811
"""Coverage for ``path-claims widen --item YOK-N`` resolution.
Pins AC-30 behavior: the shared ``cmd_widen`` parser accepts either the
positional ``claim_id`` or ``--item YOK-N`` (resolves to the one
non-terminal exclusive claim for that item). Zero matches and multiple
matches are refused with actionable USAGE messages; positional and
``--item`` are mutually exclusive at the CLI boundary.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import (
    path_claims_dispatch,
    path_claims_dispatch_amend,
    path_claims_dispatch_narrow,
    path_claims_dispatch_state,
)
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    ambient_holder_session, conn, local_human, seed_target,
    seed_test_holder_for,
)


def _seed_item(conn, *, item_id: int = 7401, project: str = "yoke") -> int:
    project_key = str(project)
    project_id = 2 if project_key == "externalwebapp" else int(project_key) if project_key.isdigit() else 1
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )
    seed_test_holder_for(conn, item_id=item_id)
    conn.commit()
    return item_id


@pytest.fixture
def patch_conn(monkeypatch, conn, ambient_holder_session):  # noqa: F811
    """Use the in-memory conn for every dispatcher surface."""
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
    monkeypatch.setattr(path_claims_dispatch_narrow, "open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_state, "open_conn", lambda: wrapper)
    return conn


def _register_claim(conn, *, item_id: int) -> int:
    """Seed an item + claim covering one path; return the new claim id."""
    actor = local_human(conn)
    seed_target(conn, path_string="src/foo.py")
    rc = path_claims_dispatch.cmd_register(
        [
            "--item", str(item_id),
            "--integration-target", "main",
            "--paths", "src/foo.py",
            "--actor-id", str(actor),
        ]
    )
    assert rc == 0
    row = conn.execute(
        "SELECT id FROM path_claims WHERE item_id = %s ORDER BY id DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    return int(row[0])


class TestWidenItemResolution:
    """AC-30: ``--item YOK-N`` resolves to the one widenable claim."""

    def test_item_flag_resolves_to_single_active_claim(
        self, patch_conn, capsys,
    ):
        item_id = _seed_item(patch_conn)
        cid = _register_claim(patch_conn, item_id=item_id)
        # Seed a sibling path target so the widen has somewhere to go.
        seed_target(patch_conn, path_string="src/bar.py")
        capsys.readouterr()
        rc = path_claims_dispatch_amend.cmd_widen(
            [
                "--item", f"YOK-{item_id}",
                "--paths", "src/bar.py",
                "--reason", "widen by item",
            ]
        )
        out, _err = capsys.readouterr()
        assert rc == 0, f"out={out!r}"
        payload = json.loads(out.strip())
        assert payload["success"] is True
        assert payload["claim"]["id"] == cid

    def test_positional_claim_id_still_works(self, patch_conn, capsys):
        item_id = _seed_item(patch_conn)
        cid = _register_claim(patch_conn, item_id=item_id)
        seed_target(patch_conn, path_string="src/bar.py")
        capsys.readouterr()
        rc = path_claims_dispatch_amend.cmd_widen(
            [
                str(cid),
                "--paths", "src/bar.py",
                "--reason", "widen by positional",
            ]
        )
        out, _err = capsys.readouterr()
        assert rc == 0
        payload = json.loads(out.strip())
        assert payload["claim"]["id"] == cid

    def test_item_with_no_claim_refused_with_usage(self, patch_conn, capsys):
        item_id = _seed_item(patch_conn, item_id=7402)
        # No claim registered.
        seed_target(patch_conn, path_string="src/baz.py")
        capsys.readouterr()
        rc = path_claims_dispatch_amend.cmd_widen(
            [
                "--item", f"YOK-{item_id}",
                "--paths", "src/baz.py",
                "--reason", "should fail",
            ]
        )
        _out, err = capsys.readouterr()
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert "no non-terminal exclusive claim" in payload["message"]
        assert f"YOK-{item_id}" in payload["message"]

    def test_item_with_multiple_claims_refused_with_usage(
        self, patch_conn, capsys,
    ):
        item_id = _seed_item(patch_conn, item_id=7403)
        # Register one exclusive claim and inject a second exclusive
        # planned/active row on the same item to simulate ambiguity.
        first = _register_claim(patch_conn, item_id=item_id)
        patch_conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, item_id, "
            "integration_target, registered_at) "
            "VALUES ('active', 'exclusive', 1, %s, 'main', "
            "'2026-05-01T00:00:00Z')",
            (item_id,),
        )
        patch_conn.commit()
        seed_target(patch_conn, path_string="src/baz.py")
        capsys.readouterr()
        rc = path_claims_dispatch_amend.cmd_widen(
            [
                "--item", f"YOK-{item_id}",
                "--paths", "src/baz.py",
                "--reason", "should fail",
            ]
        )
        _out, err = capsys.readouterr()
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert str(first) in payload["message"]
        assert "Pass the positional claim id" in payload["message"]

    def test_both_positional_and_item_rejected(self, patch_conn, capsys):
        item_id = _seed_item(patch_conn, item_id=7404)
        cid = _register_claim(patch_conn, item_id=item_id)
        seed_target(patch_conn, path_string="src/baz.py")
        capsys.readouterr()
        rc = path_claims_dispatch_amend.cmd_widen(
            [
                str(cid),
                "--item", f"YOK-{item_id}",
                "--paths", "src/baz.py",
                "--reason", "ambiguous",
            ]
        )
        _out, err = capsys.readouterr()
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert "exactly one" in payload["message"]

    def test_neither_positional_nor_item_rejected(self, patch_conn, capsys):
        capsys.readouterr()
        rc = path_claims_dispatch_amend.cmd_widen(
            [
                "--paths", "src/baz.py",
                "--reason", "nothing",
            ]
        )
        _out, err = capsys.readouterr()
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert "claim_id" in payload["message"]
        assert "--item" in payload["message"]
