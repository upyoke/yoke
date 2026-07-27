"""Executable host_control operations for branch-determining shell state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from yoke_cli.config import path_doctor

from yoke_core.domain.host_control_executor import HostControl
from yoke_core.domain.installer_campaign_recipe_operations import (
    installed_yoke,
    prepared_path,
)


@dataclass(frozen=True)
class HostBaselineResult:
    name: str
    ok: bool
    evidence: dict[str, object]
    error_code: str | None = None


def _path_state(control: HostControl) -> path_doctor.PathStateContract:
    env = {"HOME": control.home}
    if control.xdg_bin_home:
        env["XDG_BIN_HOME"] = control.xdg_bin_home
    env["SHELL"] = control.shell
    return path_doctor.resolve_path_state_contract(env=env)


def reach_fresh_host(control: HostControl) -> HostBaselineResult:
    """Reach the registered full-reset baseline for the dedicated Test Mac."""
    try:
        result = control.reset_installer_test_host()
    except Exception:
        return HostBaselineResult(
            name="fresh-host",
            ok=False,
            evidence={"paths": []},
            error_code="baseline_operation_failed",
        )
    return HostBaselineResult(
        name="fresh-host",
        ok=result.ok,
        evidence=result.evidence,
        error_code=result.error_code,
    )


def reach_shell_preconfigured(control: HostControl) -> HostBaselineResult:
    """Install the current release and verify both shell PATH surfaces."""
    name = "shell-preconfigured"
    reset = reach_fresh_host(control)
    if not reset.ok:
        return HostBaselineResult(
            name=name,
            ok=False,
            evidence={
                "operation": name,
                "reset": reset.evidence,
                "case_started": False,
            },
            error_code=reset.error_code,
        )
    try:
        fixture = control.create_fixture_operation_executor()
        setup = fixture.execute_setup_operations(
            [
                installed_yoke(evidence_name=name),
                prepared_path(evidence_name=name),
            ]
        )
        cleanup_attempts = [fixture.close()]
        if not cleanup_attempts[0].ok:
            cleanup_attempts.append(fixture.close())
        path_state = _path_state(control)
        tool_dir = path_state.tool_bin_dir
        observed = {
            surface: list(control.probe_path(surface)) for surface in ("login", "ssh")
        }
        launcher = path_state.yoke_bin
        launcher_check = control.run_machine_assertions(
            [{"argv": ["/usr/bin/test", "-x", launcher]}]
        )
    except Exception:
        return HostBaselineResult(
            name=name,
            ok=False,
            error_code="baseline_operation_failed",
            evidence={
                "operation": name,
                "reset": reset.evidence,
                "verified_property": (
                    "current Yoke launcher is executable and its tool "
                    "directory is present in login and SSH shell PATH"
                ),
            },
        )
    path_checks = {
        surface: tool_dir in entries for surface, entries in observed.items()
    }
    cleanup_ok = bool(cleanup_attempts) and cleanup_attempts[-1].ok
    ok = setup.ok and cleanup_ok and launcher_check.ok and all(path_checks.values())
    return HostBaselineResult(
        name=name,
        ok=ok,
        error_code=None if ok else "baseline_verification_failed",
        evidence={
            "operation": name,
            "reset": reset.evidence,
            "setup_operations": setup.evidence.get("operations", []),
            "cleanup_attempts": [
                {
                    "outcome": "passed" if attempt.ok else "failed",
                    "operations": attempt.evidence.get("operations", []),
                }
                for attempt in cleanup_attempts
            ],
            "tool_bin_dir": tool_dir,
            "launcher_executable": launcher_check.ok,
            "path_state": {
                "launcher": launcher,
                "launcher_present": launcher_check.ok,
                "tool_bin_dir": tool_dir,
                "login_path_present": path_checks["login"],
                "ssh_path_present": path_checks["ssh"],
            },
            "verified_property": (
                "current Yoke launcher is executable and its tool directory "
                "is present in login and SSH shell PATH"
            ),
            "observed_present": path_checks,
        },
    )


HOST_BASELINE_OPERATIONS: dict[str, Callable[[HostControl], HostBaselineResult]] = {
    "fresh-host": reach_fresh_host,
    "shell-preconfigured": reach_shell_preconfigured,
}


def run_host_baseline(control: HostControl, name: str) -> HostBaselineResult:
    """Run one registered operation; unknown prose-shaped names are refused."""
    operation = HOST_BASELINE_OPERATIONS.get(str(name))
    if operation is None:
        raise ValueError(f"unknown host baseline {name!r}")
    return operation(control)


__all__ = [
    "HOST_BASELINE_OPERATIONS",
    "HostBaselineResult",
    "reach_fresh_host",
    "reach_shell_preconfigured",
    "run_host_baseline",
]
