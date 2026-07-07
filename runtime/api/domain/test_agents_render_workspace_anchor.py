"""Workspace-anchor regressions for the agents_render reader hot path.

Lives in a sibling module so the main ``test_agents_render.py`` stays
under the file-line cap. Covers:
- AC-1: ``_resolve_reader_root(None)`` raises a structured error when
  neither ``target_root`` nor ``$YOKE_BOUND_WORKSPACE`` is supplied.
- AC-2: every reader entrypoint propagates ``target_root`` correctly
  when the caller supplies it (regression for the strict-resolver swap).
- AC-5: the byte-identity tests produce identical outcomes from any
  pytest subprocess cwd. The cross-cwd regression test is the structural
  defense — when the reader hot path falls back to ambient cwd somewhere,
  outcomes diverge across cwds and the test fails with a per-cwd diff.
- AC-6: ``_atomic_write`` refuses targets outside the calling session's
  worktree work-claim (the YOK-1784 incident shape), enforced through
  ``workspace_authority.assert_target_under_session_work_authority``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.agents_render import (
    load_canonical,
    load_claude_spec,
    render_claude_agent,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.agents_render_workspace import BOUND_WORKSPACE_ENV_VAR
from runtime.api.domain.test_agents_render_workspace_fixtures import (
    resolve_live_repo_root,
)
from yoke_core.domain.workspace_authority import SESSION_ID_ENV_VAR
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout


SESSION_REGRESSION = "test-sess-yok-1784"


# ---------------------------------------------------------------------------
# Local fixtures — kept small so the sibling module stays self-contained.
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_root() -> Path:
    """Workspace-anchored live Yoke checkout root."""
    return resolve_live_repo_root()


@pytest.fixture
def temp_agent_env(tmp_path: Path) -> Path:
    """Minimal canonical + output tree in a temp checkout root.

    Mirrors the shape of ``test_agents_render.temp_agent_env`` so the AC-2
    propagation test can exercise the reader entrypoints against an
    isolated tree without depending on the live ``runtime/agents`` files.
    """
    from yoke_core.domain.agents_render import CANONICAL_DIR, CLAUDE_OUT_DIR

    canonical = tmp_path / CANONICAL_DIR
    canonical.mkdir(parents=True)
    out = tmp_path / CLAUDE_OUT_DIR
    out.mkdir(parents=True)
    (canonical / "architect.md").write_text("You are an architect.\n")
    (canonical / "architect.claude.json").write_text(
        '{"name": "yoke-architect", "description": "Plans things", '
        '"tools": "Read, Grep", "model": "opus", "maxTurns": 20}'
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Strict resolver
# ---------------------------------------------------------------------------


def test_resolve_reader_root_raises_without_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1: reader resolver refuses None when no anchor is supplied.

    With both ``target_root`` and ``$YOKE_BOUND_WORKSPACE`` absent, the
    resolver raises ``RuntimeError`` naming both missing inputs — the
    structural defense against silent ambient-cwd reads from the
    renderer's reader hot path.
    """
    from yoke_core.domain.agents_render import _resolve_reader_root

    monkeypatch.delenv(BOUND_WORKSPACE_ENV_VAR, raising=False)
    with pytest.raises(RuntimeError) as exc:
        _resolve_reader_root(None)
    msg = str(exc.value)
    assert "target_root" in msg, "error must name the missing target_root input"
    assert BOUND_WORKSPACE_ENV_VAR in msg, (
        "error must name the missing env var so the operator knows which "
        "anchor to provide"
    )


# ---------------------------------------------------------------------------
# target_root propagation through reader entrypoints
# ---------------------------------------------------------------------------


def test_reader_helpers_propagate_target_root_when_supplied(
    temp_agent_env: Path,
) -> None:
    """AC-2: reader entrypoints honor an explicit ``target_root``.

    Confirms that the strict ``require_reader_root`` delegation does not
    regress the existing ``target_root=`` pass-through path used by every
    CLI consumer and the substrate drift surface.
    """
    rendered = render_claude_agent("architect", target_root=temp_agent_env)
    spec = load_claude_spec("architect", target_root=temp_agent_env)
    canonical = load_canonical("architect", target_root=temp_agent_env)
    assert spec["name"] == "yoke-architect"
    assert "architect" in canonical
    assert rendered.startswith("---\n")


# ---------------------------------------------------------------------------
# Cross-cwd regression
# ---------------------------------------------------------------------------


_CROSS_CWD_TARGETS = (
    "test_byte_identity",
    "test_all_agents_renderable",
    "test_no_rendered_agent_uses_retired_backlog_md_paths",
)


def _run_pytest_subprocess(*, cwd: Path, repo_root: Path) -> tuple[int, str]:
    """Invoke pytest for the three byte-identity tests with a chosen cwd.

    Anchors the test target via ``--rootdir`` and an absolute test-file
    path so test discovery is cwd-independent. ``PYTHONPATH`` and
    ``$YOKE_BOUND_WORKSPACE`` both point at ``repo_root`` so the
    fixture resolves to the same checkout regardless of cwd.
    """
    test_target = repo_root / "runtime/api/domain/test_agents_render.py"
    k_expr = " or ".join(_CROSS_CWD_TARGETS)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--no-header",
        "--rootdir",
        str(repo_root),
        "-k",
        k_expr,
        str(test_target),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(repo_root)
        + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    )
    env[BOUND_WORKSPACE_ENV_VAR] = str(repo_root)
    proc = subprocess.run(
        cmd, cwd=str(cwd), env=env,
        capture_output=True, text=True, timeout=180,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_byte_identity_tests_are_cwd_independent(
    repo_root: Path, tmp_path: Path,
) -> None:
    """AC-5: the byte-identity tests produce identical outcomes from any cwd.

    Runs the three workspace-anchored byte-identity tests in pytest
    subprocesses with three distinct cwd values (the live repo root,
    a linked-worktree path when one exists, and an unrelated ``tmp_path``).
    Exit codes must agree — either all pass (workspace-anchored reads
    resolve to the same checkout) or all fail in the same way (a real
    render-vs-disk drift the operator can investigate). A cwd-dependent
    split was the failure mode the agent hit when the reader hot
    path fell back to ``_repo_root()`` silently.
    """
    cwds: list[tuple[str, Path]] = [
        ("repo_root", repo_root),
        ("tmp_path", tmp_path),
    ]
    worktrees_dir = repo_root / ".worktrees"
    if worktrees_dir.is_dir():
        for entry in sorted(worktrees_dir.iterdir()):
            if entry.is_dir() and (entry / "runtime" / "agents").is_dir():
                cwds.append(("worktree", entry))
                break

    outcomes: list[tuple[str, int, str]] = []
    for label, cwd in cwds:
        rc, output = _run_pytest_subprocess(cwd=cwd, repo_root=repo_root)
        outcomes.append((label, rc, output))

    rcs = {rc for _, rc, _ in outcomes}
    assert len(rcs) == 1, (
        "byte-identity outcomes are cwd-dependent — the reader hot path "
        "fell back to ambient cwd somewhere. Per-cwd outcomes:\n"
        + "\n".join(
            f"  cwd={label} ({cwd}): rc={rc}\n{output[-400:]}"
            for (label, rc, output), (_, cwd) in zip(outcomes, cwds)
        )
    )


# ---------------------------------------------------------------------------
# YOK-1784 incident-shape regression
# ---------------------------------------------------------------------------


_WORKSPACE_CLAIM_SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE);
CREATE TABLE items (
    id INTEGER PRIMARY KEY, worktree TEXT, project_id INTEGER
);
CREATE TABLE epic_tasks (
    epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
    worktree TEXT, PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
    item_id INTEGER, epic_id INTEGER, task_num INTEGER,
    process_key TEXT, released_at TEXT
);
"""


def _apply_workspace_claim_schema() -> None:
    """Build the 4-table claim schema against the backend-resolved test DB.

    Zero-arg ``apply_schema`` strategy for :func:`init_test_db`: resolves its
    connection through the backend factory (``YOKE_DB`` on SQLite, the
    repointed ``YOKE_PG_DSN`` on Postgres). The facade translates the
    ``INTEGER PRIMARY KEY`` columns on Postgres so the same DDL builds on
    both engines. The code-under-test reads ``work_claims`` /
    ``items`` / ``projects`` through ``db_helpers.connect`` (the same
    backend-resolved DB), so the seed and the read hit the same database.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _WORKSPACE_CLAIM_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_worktree_claim_rows(
    db_path: str, *, repo_root: Path, config_root: Path, branch: str,
    session_id: str,
) -> None:
    """Seed the claim rows the workspace-authority helper reads.

    Routes through :func:`connect_test_db` so the inserts land in the same
    backend-resolved DB the code-under-test reads (the SQLite file under
    ``tmp_path`` on SQLite, the repointed per-test Postgres database on
    Postgres). Mirrors the original raw-seed rows: one project, one
    worktree-bearing item, one active item work-claim.
    """
    conn = connect_test_db(db_path)
    p = _p(conn)
    conn.execute(
        f"INSERT INTO projects (id, slug) VALUES ({p}, {p})",
        (1, "yoke"),
    )
    # config_root is a per-test temp dir — repo_root is the LIVE checkout here,
    # so repo_root.parent would write the temp config into the real .worktrees/.
    register_machine_checkout(config_root, repo_root, 1)
    conn.execute(
        f"INSERT INTO items (id, worktree, project_id) VALUES ({p}, {p}, {p})",
        (1784, branch, 1),
    )
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id) "
        f"VALUES ({p}, 'item', {p})",
        (session_id, 1784),
    )
    conn.commit()
    conn.close()


def test_atomic_write_refuses_main_target_under_worktree_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6 / AC-10: reproduce the YOK-1784 incident shape end-to-end.

    A session bound to a worktree work-claim invokes the substrate
    renderer's atomic-write hot path against a main-checkout target —
    exactly the misuse shape that landed 10 adapter files in main from
    a worktree-claimed session in the original incident. The helper
    must refuse before the rename step lands a wrong-tree file.

    Uses the current checkout root so the seed-source guard passes and
    this test reaches the work-claim authority check it is meant to cover.
    """
    repo_root = Path(__file__).resolve().parents[3]

    from yoke_core.domain.agents_render import _atomic_write

    out_path = repo_root / "runtime/harness/claude/agents/yoke-architect.md"

    # The seam owns the per-test DB lifecycle: a real file under tmp_path on
    # SQLite, a disposable per-test database (dropped on context exit) on
    # Postgres. YOKE_DB is bound for the test body so the code-under-test
    # (assert_target_under_session_work_authority -> db_helpers.connect) and
    # the seed (connect_test_db(db_path)) hit the same database; on Postgres
    # the binding is inert and the repointed YOKE_PG_DSN that init_test_db
    # keeps active for the context selects the per-test DB.
    with init_test_db(
        tmp_path, apply_schema=_apply_workspace_claim_schema,
    ) as db_path:
        _seed_worktree_claim_rows(
            db_path,
            repo_root=repo_root,
            config_root=tmp_path / "machine-config",
            branch="YOK-1784",
            session_id=SESSION_REGRESSION,
        )
        monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_REGRESSION)
        monkeypatch.setenv("YOKE_DB", str(db_path))

        with pytest.raises(RuntimeError) as exc:
            _atomic_write(
                out_path,
                "# rendered content\n",
                target_root=repo_root,
            )
    msg = str(exc.value)
    assert "workspace_authority" in msg
    assert "refusing write" in msg
    assert SESSION_REGRESSION in msg
    # The hot path must refuse BEFORE rendering anything to disk.
