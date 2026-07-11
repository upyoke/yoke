"""Behavioral tests for safe Docker maintenance cron convergence."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "templates/webapp/ops/docker_maintenance_converge.py"
    )
    spec = importlib.util.spec_from_file_location("docker_maintenance_converge", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCrontab:
    def __init__(self, current: str | None, *, write_failures: int = 0) -> None:
        self.current = current
        self.write_failures = write_failures
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    @staticmethod
    def _result(returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(
            ["crontab"], returncode, stdout=stdout, stderr=stderr
        )

    def __call__(self, arguments, input_text):
        args = tuple(arguments)
        self.calls.append((args, input_text))
        if args == ("crontab", "-l"):
            if self.current is None:
                return self._result(1, stderr="no crontab for deploy")
            return self._result(stdout=self.current)
        if args == ("crontab", "-"):
            if self.write_failures:
                self.write_failures -= 1
                return self._result(1, stderr="temporary crontab failure")
            self.current = input_text
            return self._result()
        raise AssertionError(f"unexpected fake crontab call: {args}")


@pytest.fixture(scope="module")
def maintenance_module() -> ModuleType:
    return _module()


def test_replaces_legacy_global_prune_and_preserves_other_entries(
    maintenance_module,
):
    custom = (
        "15 2 * * * docker image prune -af --filter until=168h "
        ">> /var/log/operator-prune.log 2>&1"
    )
    legacy = (
        "MAILTO=ops@example.com\n"
        "# documented docker image prune -af example\n"
        "30 4 * * 0 (docker builder prune -af && docker image prune -af) "
        ">> /home/deploy/docker-prune.log 2>&1\n"
        f"{custom}\n"
        "0 3 * * * backup-command\n"
    )
    canonical = maintenance_module.canonical_weekly_entry(Path("/home/deploy"))

    desired, changed = maintenance_module.reconcile_crontab(legacy, canonical)

    assert changed is True
    assert "(docker builder prune -af && docker image prune -af)" not in desired
    assert "# documented docker image prune -af example" in desired
    assert custom in desired
    assert "MAILTO=ops@example.com" in desired
    assert "0 3 * * * backup-command" in desired
    assert desired.count(canonical) == 1
    assert "docker image prune -f" in canonical
    assert "docker image prune -af" not in canonical


def test_canonical_state_is_idempotent(maintenance_module):
    canonical = maintenance_module.canonical_weekly_entry(Path("/home/deploy"))
    current = f"MAILTO=ops@example.com\n{canonical}\n"

    desired, changed = maintenance_module.reconcile_crontab(current, canonical)

    assert desired == current
    assert changed is False


def test_convergence_writes_and_verifies(maintenance_module):
    legacy = (
        "30 4 * * 0 (docker builder prune -af && docker image prune -af) "
        ">> /home/deploy/docker-prune.log 2>&1\n"
    )
    crontab = FakeCrontab(legacy)

    changed = maintenance_module.converge_maintenance(
        home=Path("/home/deploy"),
        runner=crontab,
        pause=lambda _seconds: None,
        emit=lambda _line: None,
    )

    assert changed is True
    assert crontab.current is not None
    assert "docker image prune -af" not in crontab.current
    assert "docker image prune -f" in crontab.current
    assert crontab.calls.count((("crontab", "-"), crontab.current)) == 1


def test_persistent_write_failure_is_visible(maintenance_module):
    crontab = FakeCrontab(None, write_failures=3)

    with pytest.raises(maintenance_module.MaintenanceConvergenceError) as exc:
        maintenance_module.converge_maintenance(
            home=Path("/home/deploy"),
            runner=crontab,
            pause=lambda _seconds: None,
            emit=lambda _line: None,
        )

    assert "after 3 attempts" in str(exc.value)
    assert sum(call[0] == ("crontab", "-") for call in crontab.calls) == 3


def test_remove_only_scrubs_legacy_root_authority_without_reinstalling(
    maintenance_module,
):
    custom = "15 2 * * * docker image prune -f --filter until=168h\n"
    current = (
        "0 2 * * * root-backup\n"
        "30 4 * * 0 (docker builder prune -af && docker image prune -af) "
        ">> /root/docker-prune.log 2>&1\n"
        f"{custom}"
    )
    crontab = FakeCrontab(current)

    changed = maintenance_module.converge_maintenance(
        remove_only=True,
        runner=crontab,
        pause=lambda _seconds: None,
        emit=lambda _line: None,
    )

    assert changed is True
    assert crontab.current == f"0 2 * * * root-backup\n{custom}"


def test_arbitrary_operator_image_prune_line_is_not_yoke_owned(
    maintenance_module,
):
    custom = (
        "5 1 * * * notify-start && docker image prune -a --filter until=240h "
        "&& notify-done"
    )
    canonical = maintenance_module.canonical_weekly_entry(Path("/home/deploy"))

    desired, changed = maintenance_module.reconcile_crontab(
        f"{custom}\n", canonical
    )

    assert changed is True
    assert custom in desired
    assert canonical in desired


def test_remove_only_is_noop_when_legacy_authority_has_no_image_job(
    maintenance_module,
):
    crontab = FakeCrontab("0 2 * * * root-backup\n")

    changed = maintenance_module.converge_maintenance(
        remove_only=True,
        runner=crontab,
        emit=lambda _line: None,
    )

    assert changed is False
    assert not any(call[0] == ("crontab", "-") for call in crontab.calls)
