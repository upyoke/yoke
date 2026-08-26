"""Runners bind a non-administering env so pytest owns its validation DB.

The schema-authority guard reads the ambient connection, not the target
database. A prod-flagged parent selection therefore refuses collection
while ``runtime/api/conftest.py`` converges the fixture-owned validation
database. Both runner entrypoints must apply
``environment_without_administering_selection`` so the taught
``yoke watch pytest --impacted main --bounded`` command collects under
any active connection.
"""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain.verification_tree_binding import TreeBindingVerdict
from yoke_core.tools import gate_admission, run_tests, watch_pytest
from yoke_core.tools._impacted_selection import Selection

ADMIN_ENV = "prod-db-admin"
SERVED_ENV = "prod"
PAIRED_UNIVERSE = {
    SERVED_ENV: {"transport": "https"},
    ADMIN_ENV: {"transport": "local-postgres", "prod": True},
}


class _LaunchedPytest:
    def wait(self, timeout: float | None = None) -> int:
        return 0


def _select_administering(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"active_env": ADMIN_ENV, "connections": PAIRED_UNIVERSE})
    )
    monkeypatch.setenv(machine_config_runtime.CONFIG_FILE_ENV, str(config))
    monkeypatch.setenv(ENV_OVERRIDE, ADMIN_ENV)


def test_run_tests_swaps_administering_selection_into_child_env(
    tmp_path: Path, monkeypatch
) -> None:
    _select_administering(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def launch(*_args, **kwargs):
        captured["env"] = kwargs["env"]
        return _LaunchedPytest()

    monkeypatch.setattr(run_tests, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        run_tests.process_group_reaping, "popen_in_process_group", launch
    )

    assert run_tests.run(["pkgx"], allow_tree_mismatch=True) == 0
    env = captured["env"]
    assert isinstance(env, dict)
    assert env[ENV_OVERRIDE] == SERVED_ENV
    assert env[machine_config_runtime.HOME_ENV]
    assert machine_config_runtime.CONFIG_FILE_ENV not in env


def test_impacted_selection_collects_under_prod_flagged_ambient_env(
    tmp_path: Path, monkeypatch
) -> None:
    """The taught impacted command collects against the fixture-owned DB."""
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "active_env": SERVED_ENV,
                "connections": {
                    SERVED_ENV: {"transport": "https", "prod": True},
                    ADMIN_ENV: {"transport": "local-postgres", "prod": True},
                },
            }
        )
    )
    monkeypatch.setenv(machine_config_runtime.CONFIG_FILE_ENV, str(config))
    monkeypatch.setenv(ENV_OVERRIDE, SERVED_ENV)
    checkout = Path(__file__).resolve().parents[3]
    selected = "runtime/api/domain/test_schema_authority.py"
    monkeypatch.setattr(watch_pytest, "_impacted_tree", lambda: checkout)
    monkeypatch.setattr(
        watch_pytest,
        "_impacted_selection",
        lambda *_args, **_kwargs: Selection(
            full_sweep=False,
            reason="non-administering-env regression",
            files=(selected,),
        ),
    )
    monkeypatch.setattr(
        watch_pytest.verification_tree_binding,
        "evaluate_run",
        lambda **_kwargs: TreeBindingVerdict(),
    )
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("YOKE_SESSION_ID", "test-session-autouse")
    monkeypatch.setenv(gate_admission.CAP_ENV, "0")

    rc = watch_pytest.main(
        [
            "--impacted",
            "main",
            "--bounded",
            "--allow-tree-mismatch",
            "--",
            "--collect-only",
            "-q",
            "-n",
            "0",
        ]
    )
    assert rc == 0
