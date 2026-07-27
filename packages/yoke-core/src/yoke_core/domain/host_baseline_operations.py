"""Executable host_control operations for branch-determining shell state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from yoke_cli.config import path_doctor

from yoke_core.domain.host_control_executor import HostControl


BASELINE_BEGIN = "# >>> BEGIN YOKE TEST HOST BASELINE >>>"
BASELINE_END = "# <<< END YOKE TEST HOST BASELINE <<<"


@dataclass(frozen=True)
class HostBaselineResult:
    name: str
    ok: bool
    evidence: dict[str, object]
    error_code: str | None = None


def _strip_block(text: str, begin: str, end: str) -> str:
    lines: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        marker = line.strip()
        if marker == begin:
            skipping = True
            continue
        if marker == end:
            skipping = False
            continue
        if not skipping:
            lines.append(line)
    return "".join(lines)


def _baseline_block(tool_dir: str, *, present: bool) -> str:
    quoted = tool_dir.replace("\\", "\\\\").replace('"', '\\"')
    zsh_action = (
        'path=("$__yoke_test_bin" $path)'
        if present else
        'path=("${(@)path:#$__yoke_test_bin}")'
    )
    sh_action = (
        'PATH="$__yoke_test_bin:$PATH"'
        if present else
        'PATH="$(printf \'%s\' "$PATH" | '
        'awk -v bin="$__yoke_test_bin" -v RS=: -v ORS=: '
        '\'$0 != bin\' | sed \'s/:$//\')"'
    )
    return "\n".join((
        BASELINE_BEGIN,
        f'__yoke_test_bin="{quoted}"',
        'if [ -n "${ZSH_VERSION:-}" ]; then',
        f"  {zsh_action}",
        "else",
        f"  {sh_action}",
        "fi",
        "export PATH",
        "unset __yoke_test_bin",
        BASELINE_END,
    ))


def _startup_paths(control: HostControl) -> tuple[Path, ...]:
    home = Path(control.home)
    shell = Path(control.shell).name or "zsh"
    candidates = [
        path_doctor.default_startup_file(shell, home),
        path_doctor.default_ssh_startup_file(shell, home),
    ]
    return tuple(dict.fromkeys(path for path in candidates if path is not None))


def _tool_dir(control: HostControl) -> str:
    env = {"HOME": control.home}
    if control.xdg_bin_home:
        env["XDG_BIN_HOME"] = control.xdg_bin_home
    return path_doctor.tool_bin_dir(env)


def _reach_path_state(
    control: HostControl,
    *,
    name: str,
    present: bool,
) -> HostBaselineResult:
    tool_dir = _tool_dir(control)
    paths = _startup_paths(control)
    block = _baseline_block(tool_dir, present=present)
    try:
        for path in paths:
            existing = control.read_text(str(path)) or ""
            without_product = path_doctor._strip_managed_block(existing)
            clean = _strip_block(without_product, BASELINE_BEGIN, BASELINE_END)
            if clean and not clean.endswith("\n"):
                clean += "\n"
            control.write_text(str(path), clean + block + "\n")
        observed = {
            surface: list(control.probe_path(surface))
            for surface in ("login", "ssh")
        }
    except Exception:
        return HostBaselineResult(
            name=name,
            ok=False,
            error_code="baseline_operation_failed",
            evidence={
                "operation": name,
                "startup_files": [str(path) for path in paths],
                "verified_property": "tool directory membership in shell PATH",
                "expected_present": present,
            },
        )
    checks = {
        surface: (tool_dir in entries)
        for surface, entries in observed.items()
    }
    ok = all(value is present for value in checks.values())
    return HostBaselineResult(
        name=name,
        ok=ok,
        error_code=None if ok else "baseline_verification_failed",
        evidence={
            "operation": name,
            "startup_files": [str(path) for path in paths],
            "tool_bin_dir": tool_dir,
            "verified_property": "tool directory membership in shell PATH",
            "expected_present": present,
            "observed_present": checks,
        },
    )


def reach_fresh_host(control: HostControl) -> HostBaselineResult:
    """Reach and verify the branch where shells do not inherit Yoke's bin dir."""
    return _reach_path_state(control, name="fresh-host", present=False)


def reach_shell_preconfigured(control: HostControl) -> HostBaselineResult:
    """Reach and verify the branch where shells already inherit the tool dir."""
    return _reach_path_state(
        control,
        name="shell-preconfigured",
        present=True,
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
    "BASELINE_BEGIN",
    "BASELINE_END",
    "HOST_BASELINE_OPERATIONS",
    "HostBaselineResult",
    "reach_fresh_host",
    "reach_shell_preconfigured",
    "run_host_baseline",
]
