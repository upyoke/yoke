"""db_router spawn import graph stays free of frontier/session planning."""

from __future__ import annotations

import subprocess
import sys


_BANNED_SPAWN_MODULES = (
    "yoke_core.domain.frontier_compute",
    "yoke_core.domain.frontier_rank",
    "yoke_core.domain.frontier_classify",
    "yoke_core.domain.dependency_planning",
    "yoke_core.domain.environment_bootstrap",
    "yoke_core.domain.session",
)


def test_runs_help_does_not_import_frontier_or_session_planning():
    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "importtime",
            "-m",
            "yoke_core.cli.db_router",
            "runs",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    imported = completed.stderr
    for banned in _BANNED_SPAWN_MODULES:
        assert banned not in imported, imported


def test_schema_init_imports_as_the_first_domain_module():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import yoke_core.domain.schema_init;"
                " from yoke_core.domain.work_claim_targets import conflict_match_clause;"
                " assert callable(conflict_match_clause); print('ok')"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_domain_package_still_reexports_frontier_names():
    from yoke_core.domain import FrontierItem, compute_frontier

    assert callable(compute_frontier)
    assert FrontierItem.__name__ == "FrontierItem"
