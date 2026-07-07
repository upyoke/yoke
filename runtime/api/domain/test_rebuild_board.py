from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from yoke_core.domain import rebuild_board, rebuild_board_render
from yoke_core.domain.rebuild_board_splice import splice_board
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout


@contextlib.contextmanager
def _init_repo(tmp_path: Path):
    """Yield ``(repo_root, yoke_root)`` for a Postgres-backed test repo.

    Context-managed because ``init_test_db`` provisions a disposable per-test
    Postgres database and repoints ``YOKE_PG_DSN`` only for the block's
    lifetime — the ``rebuild`` call (and the seed) must run inside the ``with``
    block. The yielded ``db_path`` token is a path-shaped compatibility slot the
    connection factory ignores; the live connection target is the repointed DSN.
    """
    repo_root = tmp_path / "repo"
    yoke_root = repo_root / ".yoke"
    backlog_dir = yoke_root / "backlog"
    backlog_dir.mkdir(parents=True)
    (backlog_dir / ".counter").write_text("1\n", encoding="utf-8")
    (yoke_root / "board.json").write_text(
        json.dumps({
            "render_path": ".yoke/BOARD.md",
            "scope": "yoke",
        }),
        encoding="utf-8",
    )
    machine_cfg = register_machine_checkout(tmp_path / "machine-config", repo_root, 1)

    # init_test_db provisions the disposable per-test Postgres database and
    # repoints YOKE_PG_DSN at it; the yielded token is a compatibility slot
    # the connection factory ignores.
    with init_test_db(yoke_root) as db_path:
        prior = dict(os.environ)
        os.environ["YOKE_DB"] = str(db_path)
        os.environ["YOKE_MACHINE_CONFIG_FILE"] = str(machine_cfg)
        try:
            conn = connect_test_db(db_path)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY,
                    slug TEXT UNIQUE,
                    name TEXT,
                    emoji TEXT DEFAULT '',
                    github_repo TEXT DEFAULT '',
                    public_item_prefix TEXT DEFAULT 'YOK'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO items (
                    id, title, type, status, priority, flow, rework_count, frozen,
                    created_at, updated_at, source, project_id, project_sequence
                ) VALUES (1, 'Test item', 'issue', 'implementing', 'medium', 'accelerated', 0, 0,
                          '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'user', 1, 1)
                """
            )
            conn.execute(
                """
                INSERT INTO projects
                    (id, slug, name, public_item_prefix, created_at)
                VALUES
                    (1, 'yoke', 'Yoke', 'YOK', '2026-01-01T00:00:00Z')
                ON CONFLICT (id) DO UPDATE SET
                    slug = excluded.slug,
                    name = excluded.name,
                    public_item_prefix = excluded.public_item_prefix
                """
            )
            conn.commit()
            conn.close()
            yield repo_root, yoke_root
        finally:
            os.environ.clear()
            os.environ.update(prior)


def test_strip_worktree_path() -> None:
    path = Path("/tmp/repo/.worktrees/YOK-1339")
    assert rebuild_board._strip_worktree_path(path) == Path("/tmp/repo")


def test_splice_board_replaces_marker_block_and_strips_conflicts() -> None:
    existing = "\n".join(
        [
            "# Title",
            "<<<<<<< HEAD",
            "noise",
            "=======",
            "noise2",
            ">>>>>>> branch",
            "<!-- YOKE:BOARD:START -->",
            "old board",
            "<!-- YOKE:BOARD:END -->",
        ]
    )
    merged = splice_board(existing, "new board", "2026-04-10T00:00:00 UTC")
    assert "old board" not in merged
    assert "new board" in merged
    assert "<<<<<<<" not in merged
    assert "<!-- YOKE:BOARD:END -->" in merged


def test_splice_board_removes_accidental_blank_before_generated_marker() -> None:
    existing = "\n<!-- YOKE:BOARD:START -->\nold board\n<!-- YOKE:BOARD:END -->\n"
    merged = splice_board(existing, "new board", "2026-04-10T00:00:00 UTC")

    assert not merged.startswith("\n")
    assert merged.startswith("<!-- YOKE:BOARD:START")
    assert "new board" in merged


def test_rebuild_writes_board_and_timestamp(tmp_path: Path) -> None:
    with _init_repo(tmp_path) as (repo_root, yoke_root):
        rc = rebuild_board.rebuild(repo_arg=str(repo_root), force=True)
        assert rc == 0
        assert rc.status == "rebuilt"
        board_path = yoke_root / "BOARD.md"
        board_text = board_path.read_text(encoding="utf-8")
        assert "Test item" in board_text
        assert "YOKE:BOARD:START" in board_text
        assert not board_text.startswith("\n")
        assert (yoke_root / "BOARD.md.ts").is_file()


def test_rebuild_refreshes_existing_board_in_place(tmp_path: Path) -> None:
    with _init_repo(tmp_path) as (repo_root, yoke_root):
        board_path = yoke_root / "BOARD.md"
        board_path.write_text(
            "\n<!-- YOKE:BOARD:START -->\nstale board\n<!-- YOKE:BOARD:END -->\n",
            encoding="utf-8",
        )
        inode_before = board_path.stat().st_ino

        rc = rebuild_board.rebuild(repo_arg=str(repo_root), force=True)

        assert rc == 0
        assert board_path.stat().st_ino == inode_before
        board_text = board_path.read_text(encoding="utf-8")
        assert not board_text.startswith("\n")
        assert "Test item" in board_text


def test_rebuild_composes_over_https_transport(tmp_path: Path, monkeypatch) -> None:
    """Same composition, https leg: the data fetch relays the envelope as
    JSON to the server boundary and the render consumes the JSON-round-
    tripped response. Simulated by patching the transport seam to route
    through a real in-process dispatch behind a wire round trip."""
    import json as _json

    from yoke_cli.transport import https as yoke_transport
    from yoke_core.domain.yoke_function_dispatch import dispatch
    from yoke_contracts.api.function_call import FunctionCallResponse

    with _init_repo(tmp_path) as (repo_root, yoke_root):
        connection = yoke_transport.HttpsConnection(
            api_url="https://api.example.test", token="tok",
        )

        def fake_relay(request, conn, **_kwargs):
            assert conn is connection
            wire_request = _json.loads(
                _json.dumps(request.model_dump(mode="json"))
            )
            response = dispatch(wire_request)
            wire_response = _json.loads(
                _json.dumps(response.model_dump(mode="json"))
            )
            return FunctionCallResponse.model_validate(wire_response)

        monkeypatch.setattr(
            yoke_transport, "resolve_https_connection", lambda *a, **k: connection,
        )
        monkeypatch.setattr(yoke_transport, "relay_https", fake_relay)

        rc = rebuild_board.rebuild(repo_arg=str(repo_root), force=True)

        assert rc == 0
        assert rc.status == "rebuilt"
        board_text = (yoke_root / "BOARD.md").read_text(encoding="utf-8")
        assert "Test item" in board_text


def test_rebuild_failed_fetch_preserves_board(tmp_path: Path, monkeypatch) -> None:
    """A failure envelope from board.data.get must not look green."""
    with _init_repo(tmp_path) as (repo_root, yoke_root):
        board = yoke_root / "BOARD.md"
        board.write_text("PRESERVED BOARD\n", encoding="utf-8")

        def failing_fetch(_payload):
            raise rebuild_board.BoardDataFetchError(
                "board.data.get failed — https_transport_failed: unreachable"
            )

        monkeypatch.setattr(rebuild_board_render, "fetch_board_data", failing_fetch)
        rc = rebuild_board.rebuild(repo_arg=str(repo_root), force=True)

        assert rc != 0
        assert rc.status == "failed"
        assert "board.data.get failed" in rc.message
        assert board.read_text(encoding="utf-8") == "PRESERVED BOARD\n"


def test_rebuild_respects_throttle(tmp_path: Path) -> None:
    with _init_repo(tmp_path) as (repo_root, yoke_root):
        board_path = yoke_root / "BOARD.md"
        rc = rebuild_board.rebuild(repo_arg=str(repo_root), force=True)
        assert rc == 0
        first = board_path.read_text(encoding="utf-8")
        ts_path = yoke_root / "BOARD.md.ts"
        ts_value = ts_path.read_text(encoding="utf-8")
        rc = rebuild_board.rebuild(repo_arg=str(repo_root))
        assert rc == 0
        assert rc.status == "throttled"
        assert rc.changed is False
        assert board_path.read_text(encoding="utf-8") == first
        assert ts_path.read_text(encoding="utf-8") == ts_value


def test_rebuild_reports_lock_skipped_without_releasing_foreign_lock(
    tmp_path: Path, monkeypatch
) -> None:
    with _init_repo(tmp_path) as (repo_root, yoke_root):
        lock = yoke_root / "BOARD.md.lock"
        lock.mkdir()
        monkeypatch.setattr(rebuild_board, "acquire_lock", lambda *_args: False)

        rc = rebuild_board.rebuild(repo_arg=str(repo_root), force=True, emit=False)

        assert rc.status == "lock_skipped"
        assert rc.exit_code == 1
        assert lock.is_dir()


def test_rebuild_db_unavailable_preserves_board_and_returns_nonzero(
    tmp_path: Path, monkeypatch
) -> None:
    """A connected-env-unavailable render must NOT look successful: the old
    board is preserved (no write) and the exit code is non-zero."""
    from yoke_core.domain import connected_env_readiness as cer

    with _init_repo(tmp_path) as (repo_root, yoke_root):
        board = yoke_root / "BOARD.md"
        board.write_text("PRESERVED BOARD\n", encoding="utf-8")

        def boom(*_args, **_kwargs):
            raise cer.ConnectedEnvUnavailable(
                "connected-env tunnel was restarted but Postgres is still "
                "unreachable. connector=local_ssh_tunnel_postgres "
                "local=127.0.0.1:6547"
            )

        monkeypatch.setattr(rebuild_board_render, "fetch_and_render", boom)
        rc = rebuild_board.rebuild(repo_arg=str(repo_root), force=True)

        assert rc != 0
        assert rc.status == "failed"
        assert board.read_text(encoding="utf-8") == "PRESERVED BOARD\n"


def test_rebuild_non_db_render_error_reports_failed(
    tmp_path: Path, monkeypatch
) -> None:
    """A renderer error preserves the old board but no longer looks green."""
    with _init_repo(tmp_path) as (repo_root, yoke_root):
        board = yoke_root / "BOARD.md"
        board.write_text("PRESERVED BOARD\n", encoding="utf-8")

        def boom(*_args, **_kwargs):
            raise ValueError("a board template bug, unrelated to the DB")

        monkeypatch.setattr(rebuild_board_render, "fetch_and_render", boom)
        rc = rebuild_board.rebuild(repo_arg=str(repo_root), force=True)

        assert rc != 0
        assert rc.status == "failed"
        assert board.read_text(encoding="utf-8") == "PRESERVED BOARD\n"
