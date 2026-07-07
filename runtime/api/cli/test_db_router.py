"""Tests for ``yoke_core.cli.db_router`` -- usage + explicit init.

Companion files split off:

- ``test_db_router_dispatch.py`` — query / items / merge / domain dispatch
- ``test_db_router_worktree.py`` — worktree path stripping + canonical
  ``YOKE_DB`` resolution from a linked worktree

Each test uses a disposable per-test Postgres DB and pins the router env
so domain modules operate in isolation. Init remains gated by
``YOKE_DB_INIT_ALLOW=1`` or the explicit ``init`` subcommand.
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Iterator, Tuple

import pytest

from yoke_core.cli import db_router
from runtime.api.fixtures.file_test_db import init_test_db


def _reset_init_flag() -> None:
    """Clear the auto-init gate between tests."""
    os.environ.pop("YOKE_DB_INIT_DONE", None)


def _run(argv: list) -> Tuple[int, str, str]:
    """Invoke ``db_router.main(argv)`` and capture stdout/stderr."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = db_router.main(argv)
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Disposable per-test Postgres DB (schema applied via
    :func:`init_test_db`) plus the auto-init/probe-gate env the tests exercise.
    ``YOKE_DB`` is pinned to the yielded path-shaped compatibility token; the
    repointed DSN is the connection target."""
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        monkeypatch.setenv("YOKE_DB_INIT_ALLOW", "1")
        monkeypatch.delenv("YOKE_DB_INIT_DONE", raising=False)
        yield Path(db_path)
        _reset_init_flag()


# ---------------------------------------------------------------------------
# Usage / error paths
# ---------------------------------------------------------------------------


class TestUsage:
    def test_no_args_returns_usage_error(self, fresh_db: Path) -> None:
        rc, out, err = _run([])
        assert rc == 2
        assert "no domain specified" in err
        assert "Usage:" in err
        assert "Domains:" in err

    def test_unknown_domain_returns_usage_error(self, fresh_db: Path) -> None:
        rc, out, err = _run(["not-a-domain"])
        assert rc == 2
        assert "unknown domain 'not-a-domain'" in err

    def test_help_no_domain_prints_usage_to_stdout(self, fresh_db: Path) -> None:
        rc, out, err = _run(["help"])
        assert rc == 0
        assert "Domains:" in out

    def test_help_for_domain_prints_hint(self, fresh_db: Path) -> None:
        rc, out, err = _run(["help", "projects"])
        assert rc == 0
        assert "projects" in err
        assert "yoke_core.domain.projects" in err

    def test_help_for_items_lists_subcommands(self, fresh_db: Path) -> None:
        rc, out, err = _run(["help", "items"])
        assert rc == 0
        assert "get" in err
        assert "update" in err

    def test_help_for_unknown_domain_reports_it(self, fresh_db: Path) -> None:
        rc, out, err = _run(["help", "nope"])
        # help on an unknown domain prints "Unknown domain: ..." and usage
        assert rc == 0
        assert "nope" in err


# ---------------------------------------------------------------------------
# Auto-init semantics
# ---------------------------------------------------------------------------


class TestAutoInit:
    def test_init_is_idempotent_within_process(
        self, fresh_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run(["help"])
        # Flag should be set after first call
        assert os.environ.get("YOKE_DB_INIT_DONE") == "1"
        # Second call is a no-op; verify by unsetting ALLOW and running again
        # against a missing DB — if init ran, it would emit the warning
        monkeypatch.delenv("YOKE_DB_INIT_ALLOW", raising=False)
        rc, out, err = _run(["help"])
        assert rc == 0
        assert "Warning: YOKE_DB" not in err

    def test_init_skipped_when_db_missing_without_allow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        missing = tmp_path / "nope.db"
        monkeypatch.setenv("YOKE_DB", str(missing))
        monkeypatch.delenv("YOKE_DB_INIT_ALLOW", raising=False)
        monkeypatch.delenv("YOKE_DB_INIT_DONE", raising=False)
        rc, out, err = _run(["help"])
        assert rc == 0
        assert "Warning: YOKE_DB" in err
        assert "Auto-init skipped" in err
        assert not missing.exists()
        _reset_init_flag()

    def test_init_subcommand_prints_and_returns_zero(self, fresh_db: Path) -> None:
        rc, out, err = _run(["init"])
        assert rc == 0
        assert "DB initialized" in out


class TestHardenedAutoInit:
    """Normal runtime commands must not run schema/domain auto-init."""

    def test_normal_command_skips_module_chain_when_not_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``items count`` on a schema-present DB without ``ALLOW=1`` must not
        trigger the ambient init module chain. Both the authority probe and
        ``items count`` resolve the per-test DSN :func:`init_test_db`
        repoints."""
        with init_test_db(tmp_path) as db_path:
            monkeypatch.setenv("YOKE_DB", db_path)
            monkeypatch.delenv("YOKE_DB_INIT_ALLOW", raising=False)
            monkeypatch.delenv("YOKE_DB_INIT_DONE", raising=False)

            ran = {"module_chain": False}

            def fake_chain(repo_root):
                ran["module_chain"] = True

            monkeypatch.setattr(db_router, "_run_init_modules", fake_chain)
            rc, out, err = _run(["items", "count"])
            assert ran["module_chain"] is False, (
                "normal command must not trigger _run_init_modules"
            )
            _reset_init_flag()

    def test_init_subcommand_runs_module_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit ``init`` still runs the module chain."""
        db_path = tmp_path / "yoke.db"
        monkeypatch.setenv("YOKE_DB", str(db_path))
        monkeypatch.setenv("YOKE_DB_INIT_ALLOW", "1")
        monkeypatch.delenv("YOKE_DB_INIT_DONE", raising=False)

        ran = {"module_chain": False}

        def fake_chain(repo_root):
            ran["module_chain"] = True
            # Simulate DB creation so the probe downstream is happy.
            db_path.touch()
            os.environ["YOKE_DB_INIT_DONE"] = "1"

        monkeypatch.setattr(db_router, "_run_init_modules", fake_chain)
        rc, out, err = _run(["init"])
        assert rc == 0
        assert ran["module_chain"] is True
        _reset_init_flag()

    def test_allow_env_permits_module_chain_for_any_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``YOKE_DB_INIT_ALLOW=1`` opts the process into ambient
        bootstrap (test fixtures, first-run provisioning)."""
        db_path = tmp_path / "yoke.db"
        monkeypatch.setenv("YOKE_DB", str(db_path))
        monkeypatch.setenv("YOKE_DB_INIT_ALLOW", "1")
        monkeypatch.delenv("YOKE_DB_INIT_DONE", raising=False)

        ran = {"module_chain": False}

        def fake_chain(repo_root):
            ran["module_chain"] = True

        monkeypatch.setattr(db_router, "_run_init_modules", fake_chain)
        rc, out, err = _run(["help"])
        assert ran["module_chain"] is True
        _reset_init_flag()

    def test_help_skips_schema_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``help`` runs even when only a stray legacy DB token exists
        (no probe short-circuit)."""
        db_path = tmp_path / "yoke.db"
        db_path.touch()
        monkeypatch.setenv("YOKE_DB", str(db_path))
        monkeypatch.delenv("YOKE_DB_INIT_ALLOW", raising=False)
        monkeypatch.delenv("YOKE_DB_INIT_DONE", raising=False)
        monkeypatch.setattr(
            db_router, "_run_init_modules", lambda _r: None
        )
        rc, out, err = _run(["help"])
        assert rc == 0
        _reset_init_flag()
