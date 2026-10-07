"""A server birth interrupted after its born-ness commit resumes on the next boot."""

from __future__ import annotations

import sys
import types

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_contracts.first_admin_name import ADMIN_NAME_ENV
from yoke_core.api import server_entrypoint


def test_interrupted_birth_completes_on_next_boot(monkeypatch, capsys) -> None:
    """A birth that dies after the born-ness commit resumes on the next boot.

    The born-ness sentinel commits early while the admin token mints last, so
    the next boot detects the born-but-tokenless shape, re-enters the
    idempotent birth, and mints + prints the one-time token before serving.
    """
    from yoke_core.domain import environment_bootstrap
    from yoke_core.domain.api_tokens import (
        INITIAL_ADMIN_TOKEN_NAME,
        TOKEN_PREFIX,
        verify_token,
    )

    name = pg_testdb.create_test_database()  # empty: no schema, no rows
    monkeypatch.setenv("YOKE_PG_DSN", pg_testdb.dsn_for_test_database(name))
    monkeypatch.setenv(ADMIN_NAME_ENV, "Ada Lovelace")
    fake_uvicorn = types.ModuleType("uvicorn")
    served: list[bool] = []
    fake_uvicorn.run = lambda *a, **k: served.append(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    real_populate = environment_bootstrap.populate_event_registry
    fail = {"on": True}

    def _flaky_populate(*args, **kwargs):  # noqa: ANN001
        if fail["on"]:
            raise RuntimeError("birth interrupted")
        return real_populate(*args, **kwargs)

    monkeypatch.setattr(
        environment_bootstrap,
        "populate_event_registry",
        _flaky_populate,
    )
    try:
        with pytest.raises(RuntimeError, match="birth interrupted"):
            server_entrypoint.main(argv=[])
        assert served == []
        assert server_entrypoint.FIRST_BOOT_TOKEN_MARKER not in capsys.readouterr().out

        # The failed boot left the half-born shape: the born-ness sentinel
        # committed, the credential never minted.
        conn = pg_testdb.connect_test_database(name)
        try:
            orgs = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()
            assert int(orgs[0]) == 1
            tokens = conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()
            assert int(tokens[0]) == 0
        finally:
            conn.close()

        fail["on"] = False
        rc = server_entrypoint.main(argv=[])
        assert rc == 0
        assert served == [True]
        out = capsys.readouterr().out
        assert out.count(server_entrypoint.FIRST_BOOT_TOKEN_MARKER) == 1
        raw_token = next(
            line.strip()
            for line in out.splitlines()
            if line.strip().startswith(TOKEN_PREFIX)
        )
        conn = pg_testdb.connect_test_database(name)
        try:
            verified = verify_token(conn, raw_token)
            assert verified.name == INITIAL_ADMIN_TOKEN_NAME
        finally:
            conn.close()

        # A completed universe boots the idempotent born path: no re-mint,
        # no re-print.
        rc = server_entrypoint.main(argv=[])
        assert rc == 0
        out = capsys.readouterr().out
        assert server_entrypoint.FIRST_BOOT_TOKEN_MARKER not in out
        conn = pg_testdb.connect_test_database(name)
        try:
            tokens = conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()
            assert int(tokens[0]) == 1
        finally:
            conn.close()
    finally:
        pg_testdb.drop_test_database(name)
