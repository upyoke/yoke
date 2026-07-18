"""Coverage for the ``path-claims narrow`` dispatch handler.

Pins the explicit ``--drop-paths`` / ``--keep-paths`` flag pair, the
mutual-exclusivity rejection, the bare ``--paths`` rejection, and the
keep-set translation that converts kept paths into the equivalent
drop-set the domain function already takes.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from yoke_core.domain import (
    path_claims_dispatch,
    path_claims_dispatch_amend,
    path_claims_dispatch_narrow,
    path_claims_dispatch_state,
)
from yoke_core.api import service_client_path_claims
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    ambient_holder_session, conn, local_human, seed_target,
    seed_test_holder_for,
)


def _git(repo, *args):
    full_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False, env=full_env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    (tmp_path / "README.md").write_text("# repo\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def _seed_item(conn, *, item_id: int = 9001, project: str = "yoke") -> int:
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
    monkeypatch.setattr(path_claims_dispatch_narrow, "open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_state, "open_conn", lambda: wrapper)
    return conn


def _capture(capsys):
    captured = capsys.readouterr()
    return captured.out, captured.err


def _register_two_path_claim(conn, *, repo_path: str) -> tuple[int, int, int]:
    """Seed an item + register a claim covering two real paths.

    Returns (claim_id, target_a_id, target_b_id).
    """
    actor = local_human(conn)
    item_id = _seed_item(conn)
    ta = seed_target(conn, path_string="src/foo.py")
    tb = seed_target(conn, path_string="src/bar.py")
    rc = path_claims_dispatch.cmd_register(
        [
            "--item", str(item_id),
            "--integration-target", "main",
            "--paths", "src/foo.py,src/bar.py",
            "--actor-id", str(actor),
        ]
    )
    assert rc == 0
    # Pull claim id from the most recent insert.
    row = conn.execute(
        "SELECT id FROM path_claims WHERE item_id = %s ORDER BY id DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    return int(row[0]), ta, tb


class TestNarrowFlagPair:
    def test_drop_paths_drops_target_and_records_amendment(
        self, patch_conn, capsys, repo
    ):
        cid, ta, tb = _register_two_path_claim(patch_conn, repo_path=str(repo))
        capsys.readouterr()
        rc = path_claims_dispatch_narrow.cmd_narrow(
            [
                str(cid),
                "--drop-paths", "src/bar.py",
                "--reason", "drop unused",
                "--repo-path", str(repo),
            ]
        )
        out, _ = _capture(capsys)
        assert rc == 0
        payload = json.loads(out.strip())
        assert payload["success"] is True
        assert payload["claim"]["target_ids"] == [ta]
        # Amendment payload preserves the existing narrow shape.
        amendment_row = patch_conn.execute(
            "SELECT amendment_kind, payload FROM path_claim_amendments "
            "WHERE id = %s",
            (payload["amendment_id"],),
        ).fetchone()
        assert amendment_row[0] == "narrow"
        assert json.loads(amendment_row[1])["removed"] == [tb]

    def test_keep_paths_translates_to_drop_set(
        self, patch_conn, capsys, repo
    ):
        cid, ta, tb = _register_two_path_claim(patch_conn, repo_path=str(repo))
        capsys.readouterr()
        rc = path_claims_dispatch_narrow.cmd_narrow(
            [
                str(cid),
                "--keep-paths", "src/foo.py",
                "--reason", "keep only foo",
                "--repo-path", str(repo),
            ]
        )
        out, _ = _capture(capsys)
        assert rc == 0
        payload = json.loads(out.strip())
        assert payload["claim"]["target_ids"] == [ta]
        amendment_row = patch_conn.execute(
            "SELECT payload FROM path_claim_amendments WHERE id = %s",
            (payload["amendment_id"],),
        ).fetchone()
        # The translated drop set covers everything in declared minus keep.
        assert json.loads(amendment_row[0])["removed"] == [tb]


class TestNarrowFlagPairRejections:
    def test_bare_paths_is_rejected_naming_both_replacements(
        self, patch_conn, capsys, repo
    ):
        cid, _ta, _tb = _register_two_path_claim(
            patch_conn, repo_path=str(repo)
        )
        capsys.readouterr()
        rc = path_claims_dispatch_narrow.cmd_narrow(
            [
                str(cid),
                "--paths", "src/bar.py",
                "--reason", "drop unused",
                "--repo-path", str(repo),
            ]
        )
        _out, err = _capture(capsys)
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert "--drop-paths" in payload["message"]
        assert "--keep-paths" in payload["message"]

    def test_mutually_exclusive_when_both_passed(
        self, patch_conn, capsys, repo
    ):
        cid, _ta, _tb = _register_two_path_claim(
            patch_conn, repo_path=str(repo)
        )
        capsys.readouterr()
        rc = path_claims_dispatch_narrow.cmd_narrow(
            [
                str(cid),
                "--drop-paths", "src/bar.py",
                "--keep-paths", "src/foo.py",
                "--reason", "ambiguous",
                "--repo-path", str(repo),
            ]
        )
        _out, err = _capture(capsys)
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert "--drop-paths" in payload["message"]
        assert "--keep-paths" in payload["message"]
        assert "mutually exclusive" in payload["message"]

    def test_keep_paths_rejects_unknown_path(
        self, patch_conn, capsys, repo
    ):
        cid, _ta, _tb = _register_two_path_claim(
            patch_conn, repo_path=str(repo)
        )
        capsys.readouterr()
        rc = path_claims_dispatch_narrow.cmd_narrow(
            [
                str(cid),
                "--keep-paths", "src/foo.py,src/never_added.py",
                "--reason", "typo",
                "--repo-path", str(repo),
            ]
        )
        _out, err = _capture(capsys)
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert "src/never_added.py" in payload["message"]
        assert "path-claims widen" in payload["message"]

    def test_keep_paths_rejects_empty_keep_set(
        self, patch_conn, capsys, repo
    ):
        cid, _ta, _tb = _register_two_path_claim(
            patch_conn, repo_path=str(repo)
        )
        capsys.readouterr()
        rc = path_claims_dispatch_narrow.cmd_narrow(
            [
                str(cid),
                "--keep-paths", "",
                "--reason", "empty",
                "--repo-path", str(repo),
            ]
        )
        _out, err = _capture(capsys)
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert "--keep-paths" in payload["message"]

    def test_neither_flag_emits_usage_error(
        self, patch_conn, capsys, repo
    ):
        cid, _ta, _tb = _register_two_path_claim(
            patch_conn, repo_path=str(repo)
        )
        capsys.readouterr()
        rc = path_claims_dispatch_narrow.cmd_narrow(
            [
                str(cid),
                "--reason", "no flags",
                "--repo-path", str(repo),
            ]
        )
        _out, err = _capture(capsys)
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"

    def test_help_advertises_explicit_flags_only(self, capsys):
        rc = path_claims_dispatch_narrow.cmd_narrow(["--help"])
        out, err = _capture(capsys)
        assert rc == 0
        assert "--drop-paths" in out
        assert "--keep-paths" in out
        assert "--paths" not in out
        assert err == ""


class TestNarrowFacadeIntegration:
    def test_main_routes_narrow_to_new_handler(
        self, patch_conn, capsys, repo
    ):
        cid, ta, _tb = _register_two_path_claim(
            patch_conn, repo_path=str(repo)
        )
        capsys.readouterr()
        rc = path_claims_dispatch.main(
            [
                "narrow",
                str(cid),
                "--keep-paths", "src/foo.py",
                "--reason", "via facade",
                "--repo-path", str(repo),
            ]
        )
        out, _ = _capture(capsys)
        assert rc == 0
        payload = json.loads(out.strip())
        assert payload["claim"]["target_ids"] == [ta]

    @pytest.mark.parametrize(
        ("flag", "value"),
        [
            ("--drop-paths", "src/bar.py"),
            ("--keep-paths", "src/foo.py"),
        ],
    )
    def test_service_client_wrapper_delegates_to_narrow_handler(
        self, patch_conn, capsys, repo, flag, value
    ):
        cid, ta, _tb = _register_two_path_claim(
            patch_conn, repo_path=str(repo)
        )
        capsys.readouterr()
        rc = service_client_path_claims.cmd_path_claim_narrow(
            [
                str(cid),
                flag, value,
                "--reason", "via service client",
                "--repo-path", str(repo),
            ]
        )
        out, _ = _capture(capsys)
        assert rc == 0
        payload = json.loads(out.strip())
        assert payload["claim"]["target_ids"] == [ta]
