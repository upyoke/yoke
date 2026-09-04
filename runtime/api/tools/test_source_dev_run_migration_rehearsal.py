# ruff: noqa: F811

"""Claimed-lane source execution covers migration-local imports."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.migration_apply_test_helpers import (
    _seed_apply_item,
    apply_env,  # noqa: F401 - fixture registration
)
from runtime.api.test_backlog import tmp_db  # noqa: F401 - fixture dependency
from yoke_core.tools import _source_pythonpath, source_dev_run


def test_source_runner_rehearses_migration_with_lane_only_import(
    apply_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree = Path(apply_env["worktree"])
    (worktree / "packages/yoke-core/src/yoke_core").mkdir(
        parents=True,
        exist_ok=True,
    )
    (worktree / "lane_only_migration_support.py").write_text(
        "TABLE_NAME = 'lane_import_widgets'\n",
        encoding="utf-8",
    )
    (apply_env["modules_dir"] / "lane_import_migration.py").write_text(
        "from lane_only_migration_support import TABLE_NAME\n\n"
        "def apply(conn):\n"
        "    conn.execute(f'CREATE TABLE {TABLE_NAME} (id INTEGER PRIMARY KEY)')\n",
        encoding="utf-8",
    )
    item_id = 5040
    _seed_apply_item(
        apply_env["control_db"],
        item_id=item_id,
        modules=["lane_import_migration"],
    )
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda *_args: (worktree, None, None),
    )
    monkeypatch.setattr(
        _source_pythonpath,
        "import_origins",
        lambda _root, env: ({"runtime": str(worktree / "runtime")}, None),
    )

    probe = (
        "from pathlib import Path; "
        "from yoke_core.domain.migration_apply import format_rehearse, rehearse; "
        f"result = rehearse({item_id}, session_id='test-session', "
        f"control_db_path={apply_env['control_db']!r}, "
        f"worktree_path=Path({str(worktree)!r})); "
        "print(format_rehearse(result)); "
        "raise SystemExit(0 if result.all_succeeded else 1)"
    )

    assert source_dev_run.run(["python3", "-c", probe]) == 0
