"""Run small live installer TUI assignments from ledgered SSH hosts."""

from __future__ import annotations

import argparse
import math
import shlex
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_capture as capture_tool
from yoke_core.tools.installer_live_tui_fleet import scp_argv, ssh_argv
from yoke_core.tools.installer_live_tui_harness import scan_secret_markers_in_paths


DEFAULT_PANE = "ob"
DEFAULT_START_DELAY = 3.0
DEFAULT_STEP_DELAY = 0.5
DEFAULT_MAX_WALL_SECONDS = 1200.0
DEFAULT_CAPTURE_READY_ATTEMPTS = 20
DEFAULT_CAPTURE_READY_DELAY = 0.5
FILE_PASTE_KEY_PREFIX = "paste_file:"


@dataclass(frozen=True)
class ScenarioAction:
    step: str
    keys: tuple[str, ...] = ()
    capture: bool = True


@dataclass(frozen=True)
class ScenarioRunResult:
    ok: bool
    report_path: str
    assignment_id: str
    scenario_id: str
    host_id: str
    overall_result: str
    capture_count: int
    screenshot_count: int
    failure: str


def run_remote_sequence(
    *,
    ledger_path: Path,
    campaign_root: Path,
    assignment_id: str,
    scenario_id: str,
    command: str,
    actions: Sequence[ScenarioAction],
    expected_text: Sequence[str] = (),
    post_checks: Sequence[str] = (),
    stage_files: Sequence[dict[str, object]] = (),
    execution_mode: str = "tmux",
    expected_return_codes: Sequence[int] = (0,),
    host_id: str | None = None,
    pane: str = DEFAULT_PANE,
    start_delay: float = DEFAULT_START_DELAY,
    step_delay: float = DEFAULT_STEP_DELAY,
    max_wall_seconds: float | None = DEFAULT_MAX_WALL_SECONDS,
    runner: capture_tool.CommandRunner | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> ScenarioRunResult:
    if not actions:
        raise ValueError("at least one scenario action is required")
    normalized_max_wall_seconds = _normalize_max_wall_seconds(max_wall_seconds)
    started_monotonic = clock()

    def enforce_wall_clock(stage: str) -> None:
        _enforce_wall_clock(
            started_monotonic=started_monotonic,
            max_wall_seconds=normalized_max_wall_seconds,
            stage=stage,
            clock=clock,
        )

    selected_runner = runner or capture_tool.CommandRunner()
    connection = capture_tool.host_connection_from_ledger(
        ledger_path,
        host_id,
    )
    started_at = _now_iso()
    _archive_existing_scenario_output(
        campaign_root=campaign_root,
        assignment_id=assignment_id,
        scenario_id=scenario_id,
        archive_id=started_at,
    )
    captures: list[dict[str, object]] = []
    screenshots: list[dict[str, object]] = []
    all_text: list[str] = []
    capture_failures: list[str] = []
    failure = ""
    secret_free = True
    tmux_started = False
    try:
        _stage_files(
            stage_files,
            campaign_root=campaign_root,
            assignment_id=assignment_id,
            scenario_id=scenario_id,
            runner=selected_runner,
            connection=connection,
        )
        if execution_mode == "ssh-command":
            return _run_remote_command_once(
                runner=selected_runner,
                connection=connection,
                campaign_root=campaign_root,
                assignment_id=assignment_id,
                scenario_id=scenario_id,
                command=command,
                actions=actions,
                expected_text=expected_text,
                post_checks=post_checks,
                expected_return_codes=expected_return_codes,
                started_at=started_at,
                max_wall_seconds=normalized_max_wall_seconds,
                started_monotonic=started_monotonic,
                clock=clock,
            )
        if execution_mode != "tmux":
            raise ValueError(f"unsupported execution_mode: {execution_mode}")
        enforce_wall_clock("stage files")
        _start_remote_tmux(
            runner=selected_runner,
            connection=connection,
            pane=pane,
            command=command,
        )
        tmux_started = True
        sleeper(start_delay)
        enforce_wall_clock("start delay")
        for action in actions:
            enforce_wall_clock(f"{action.step} before keys")
            if action.keys:
                _send_remote_action_keys(
                    runner=selected_runner,
                    connection=connection,
                    pane=pane,
                    keys=action.keys,
                )
                sleeper(step_delay)
                enforce_wall_clock(f"{action.step} after keys")
            if not action.capture:
                continue
            text = _capture_remote_tmux_pane_when_ready(
                runner=selected_runner,
                connection=connection,
                pane=pane,
                step=action.step,
                sleeper=sleeper,
                enforce_wall_clock=enforce_wall_clock,
            )
            if not _capture_has_visible_text(text):
                capture_failures.append(
                    f"{action.step} capture was blank after "
                    f"{DEFAULT_CAPTURE_READY_ATTEMPTS} attempts"
                )
            all_text.append(text)
            evidence = capture_tool.write_paired_evidence(
                campaign_root=campaign_root,
                assignment_id=assignment_id,
                scenario_id=scenario_id,
                step=action.step,
                text=text,
            )
            captures.append(
                {
                    "name": Path(evidence.capture_path).name,
                    "path": evidence.capture_path,
                    "sha256": evidence.text_sha256,
                    "bytes": evidence.text_bytes,
                }
            )
            screenshots.append(
                {
                    "name": Path(evidence.screenshot_path).name,
                    "path": evidence.screenshot_path,
                    "matches_capture": Path(evidence.capture_path).name,
                    "sha256": evidence.screenshot_sha256,
                    "bytes": evidence.screenshot_bytes,
                }
            )
            enforce_wall_clock(f"{action.step} capture")
        combined_text = "\n".join(all_text)
        failure = _join_failure(
            _text_assertion_failure(combined_text, expected_text, post_checks),
            "; ".join(capture_failures),
        )
        secret_findings = scan_secret_markers_in_paths(
            [
                campaign_root / "captures" / assignment_id / scenario_id,
                campaign_root / "screenshots" / assignment_id / scenario_id,
            ]
        )
        if secret_findings:
            secret_free = False
            failure = "secret markers found in retained evidence"
        failure = _join_failure(
            failure,
            _tmux_exit_assertion_failure(
                post_checks,
                runner=selected_runner,
                connection=connection,
                pane=pane,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        failure = str(exc)
    finally:
        if tmux_started:
            _stop_remote_tmux(
                runner=selected_runner,
                connection=connection,
                pane=pane,
            )

    overall_result = "fail" if failure else "pass"
    report_path = _write_report(
        campaign_root=campaign_root,
        assignment_id=assignment_id,
        scenario_id=scenario_id,
        host_id=connection.host_id,
        started_at=started_at,
        completed_at=_now_iso(),
        overall_result=overall_result,
        captures=captures,
        screenshots=screenshots,
        expected_text=expected_text,
        post_checks=post_checks,
        failure=failure,
        secret_free=secret_free,
        max_wall_seconds=normalized_max_wall_seconds,
    )
    return ScenarioRunResult(
        ok=not failure,
        report_path=str(report_path),
        assignment_id=assignment_id,
        scenario_id=scenario_id,
        host_id=connection.host_id,
        overall_result=overall_result,
        capture_count=len(captures),
        screenshot_count=len(screenshots),
        failure=failure,
    )


def parse_action(raw: str) -> ScenarioAction:
    step, separator, raw_keys = raw.partition(":")
    keys = tuple(key for key in raw_keys.split(",") if key) if separator else ()
    return ScenarioAction(step=step, keys=keys)


def _send_remote_action_keys(
    *,
    runner: capture_tool.CommandRunner,
    connection: capture_tool.LedgerHostConnection,
    pane: str,
    keys: Sequence[str],
) -> None:
    literal_keys: list[str] = []

    def flush_literal_keys() -> None:
        if not literal_keys:
            return
        capture_tool.send_remote_tmux_keys(
            key_path=connection.key_path,
            public_ip=connection.public_ip,
            ssh_user=connection.ssh_user,
            pane=pane,
            keys=tuple(literal_keys),
            runner=runner,
        )
        literal_keys.clear()

    for key in keys:
        if key.startswith(FILE_PASTE_KEY_PREFIX):
            flush_literal_keys()
            file_path = key.removeprefix(FILE_PASTE_KEY_PREFIX).strip()
            if not file_path:
                raise ValueError("paste_file key requires a remote file path")
            capture_tool.paste_remote_tmux_file(
                key_path=connection.key_path,
                public_ip=connection.public_ip,
                ssh_user=connection.ssh_user,
                pane=pane,
                file_path=file_path,
                runner=runner,
            )
            continue
        literal_keys.append(key)
    flush_literal_keys()


def _parse_stage_file(raw: str) -> dict[str, object]:
    source, separator, remote_path = raw.partition("=")
    if not separator or not source or not remote_path:
        raise ValueError("--stage-file must be LOCAL_PATH=REMOTE_PATH")
    return {"source_path": source, "remote_path": remote_path}


def _parse_stage_url(raw: str) -> dict[str, object]:
    source, separator, remote_path = raw.partition("=")
    if not separator or not source or not remote_path:
        raise ValueError("--stage-url must be URL=REMOTE_PATH")
    return {"source_url": source, "remote_path": remote_path}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.installer_live_tui_runner",
        description="Run a small ledgered SSH live-TUI assignment and write a report.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    run_ssh = subparsers.add_parser("run-ssh")
    run_ssh.add_argument("--ledger", required=True, type=Path)
    run_ssh.add_argument("--campaign-root", required=True, type=Path)
    run_ssh.add_argument("--assignment-id", required=True)
    run_ssh.add_argument("--scenario-id", required=True)
    run_ssh.add_argument("--command", dest="launch_command", required=True)
    run_ssh.add_argument("--host-id")
    run_ssh.add_argument("--pane", default=DEFAULT_PANE)
    run_ssh.add_argument(
        "--action",
        action="append",
        required=True,
        help="Capture step, optionally followed by tmux keys: 010-after-down:Down",
    )
    run_ssh.add_argument("--expect", action="append", default=[])
    run_ssh.add_argument("--post-check", action="append", default=[])
    run_ssh.add_argument("--expect-rc", action="append", type=int, default=[])
    run_ssh.add_argument(
        "--execution-mode",
        choices=("tmux", "ssh-command"),
        default="tmux",
    )
    run_ssh.add_argument(
        "--stage-file",
        action="append",
        default=[],
        help="Copy a local file before launch, as LOCAL_PATH=REMOTE_PATH.",
    )
    run_ssh.add_argument(
        "--stage-url",
        action="append",
        default=[],
        help="Download and copy a URL before launch, as URL=REMOTE_PATH.",
    )
    run_ssh.add_argument("--start-delay", type=float, default=DEFAULT_START_DELAY)
    run_ssh.add_argument("--step-delay", type=float, default=DEFAULT_STEP_DELAY)
    run_ssh.add_argument(
        "--max-wall-seconds",
        type=float,
        default=DEFAULT_MAX_WALL_SECONDS,
        help="Maximum scenario wall-clock seconds; pass 0 to disable.",
    )
    run_ssh.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.subcommand == "run-ssh":
            result = run_remote_sequence(
                ledger_path=args.ledger.expanduser(),
                campaign_root=args.campaign_root.expanduser(),
                assignment_id=args.assignment_id,
                scenario_id=args.scenario_id,
                command=args.launch_command,
                host_id=args.host_id,
                pane=args.pane,
                actions=[parse_action(raw) for raw in args.action],
                expected_text=args.expect,
                post_checks=args.post_check,
                stage_files=[
                    *(_parse_stage_file(raw) for raw in args.stage_file),
                    *(_parse_stage_url(raw) for raw in args.stage_url),
                ],
                execution_mode=args.execution_mode,
                expected_return_codes=args.expect_rc or [0],
                start_delay=args.start_delay,
                step_delay=args.step_delay,
                max_wall_seconds=args.max_wall_seconds,
            )
            return _emit(asdict(result), args.json, rc=0 if result.ok else 1)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.subcommand}")


def _stage_files(
    stage_files: Sequence[dict[str, object]],
    *,
    campaign_root: Path,
    assignment_id: str,
    scenario_id: str,
    runner: capture_tool.CommandRunner,
    connection: capture_tool.LedgerHostConnection,
) -> None:
    for index, raw in enumerate(stage_files, start=1):
        remote_path = str(raw.get("remote_path") or "").strip()
        if not remote_path:
            raise ValueError("stage file remote_path is required")
        local_path = _stage_source_path(
            raw,
            campaign_root=campaign_root,
            assignment_id=assignment_id,
            scenario_id=scenario_id,
            index=index,
            remote_path=remote_path,
        )
        result = runner.run(
            scp_argv(
                connection.key_path,
                connection.public_ip,
                local_path,
                remote_path,
                ssh_user=connection.ssh_user,
            ),
            timeout=60,
        )
        if result.returncode != 0:
            detail = "\n".join(
                part.strip() for part in (result.stderr, result.stdout) if part.strip()
            )
            raise RuntimeError(
                f"stage file copy failed for {remote_path} rc={result.returncode}: "
                f"{detail}"
            )


def _stage_source_path(
    raw: dict[str, object],
    *,
    campaign_root: Path,
    assignment_id: str,
    scenario_id: str,
    index: int,
    remote_path: str,
) -> Path:
    source_path = str(raw.get("source_path") or "").strip()
    source_url = str(raw.get("source_url") or "").strip()
    if bool(source_path) == bool(source_url):
        raise ValueError("stage file needs exactly one of source_path or source_url")
    if source_path:
        path = Path(source_path).expanduser()
        if not path.is_file():
            raise ValueError(f"stage source_path is not readable: {path}")
        return path
    stage_dir = campaign_root / "raw-host-staging" / assignment_id / scenario_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(remote_path).name or f"stage-{index:03d}"
    path = stage_dir / f"{index:03d}-{filename}"
    with urllib.request.urlopen(source_url, timeout=60) as response:
        path.write_bytes(response.read())
    return path


def _run_remote_command_once(
    *,
    runner: capture_tool.CommandRunner,
    connection: capture_tool.LedgerHostConnection,
    campaign_root: Path,
    assignment_id: str,
    scenario_id: str,
    command: str,
    actions: Sequence[ScenarioAction],
    expected_text: Sequence[str],
    post_checks: Sequence[str],
    expected_return_codes: Sequence[int],
    started_at: str,
    max_wall_seconds: float | None,
    started_monotonic: float,
    clock: Callable[[], float],
) -> ScenarioRunResult:
    if len(actions) != 1:
        raise ValueError("ssh-command execution needs exactly one capture action")
    action = actions[0]
    if action.keys:
        raise ValueError("ssh-command execution does not support tmux keys")
    _enforce_wall_clock(
        started_monotonic=started_monotonic,
        max_wall_seconds=max_wall_seconds,
        stage=f"{action.step} before command",
        clock=clock,
    )
    result = runner.run(
        ssh_argv(
            connection.key_path,
            connection.public_ip,
            command,
            ssh_user=connection.ssh_user,
        ),
        timeout=_remaining_command_timeout(
            default_timeout=600,
            started_monotonic=started_monotonic,
            max_wall_seconds=max_wall_seconds,
            clock=clock,
        ),
    )
    _enforce_wall_clock(
        started_monotonic=started_monotonic,
        max_wall_seconds=max_wall_seconds,
        stage=f"{action.step} command",
        clock=clock,
    )
    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    evidence = capture_tool.write_paired_evidence(
        campaign_root=campaign_root,
        assignment_id=assignment_id,
        scenario_id=scenario_id,
        step=action.step,
        text=text,
    )
    captures = [
        {
            "name": Path(evidence.capture_path).name,
            "path": evidence.capture_path,
            "sha256": evidence.text_sha256,
            "bytes": evidence.text_bytes,
        }
    ]
    screenshots = [
        {
            "name": Path(evidence.screenshot_path).name,
            "path": evidence.screenshot_path,
            "matches_capture": Path(evidence.capture_path).name,
            "sha256": evidence.screenshot_sha256,
            "bytes": evidence.screenshot_bytes,
        }
    ]
    failure = _text_assertion_failure(text, expected_text, post_checks)
    if result.returncode not in set(expected_return_codes):
        expected = ", ".join(str(value) for value in expected_return_codes)
        failure = _join_failure(
            failure,
            f"return code {result.returncode} was not in expected set: {expected}",
        )
    secret_findings = scan_secret_markers_in_paths(
        [
            campaign_root / "captures" / assignment_id / scenario_id,
            campaign_root / "screenshots" / assignment_id / scenario_id,
        ]
    )
    secret_free = not secret_findings
    if secret_findings:
        failure = _join_failure(failure, "secret markers found in retained evidence")
    overall_result = "fail" if failure else "pass"
    report_path = _write_report(
        campaign_root=campaign_root,
        assignment_id=assignment_id,
        scenario_id=scenario_id,
        host_id=connection.host_id,
        started_at=started_at,
        completed_at=_now_iso(),
        overall_result=overall_result,
        captures=captures,
        screenshots=screenshots,
        expected_text=expected_text,
        post_checks=post_checks,
        failure=failure,
        secret_free=secret_free,
        max_wall_seconds=max_wall_seconds,
    )
    return ScenarioRunResult(
        ok=not failure,
        report_path=str(report_path),
        assignment_id=assignment_id,
        scenario_id=scenario_id,
        host_id=connection.host_id,
        overall_result=overall_result,
        capture_count=len(captures),
        screenshot_count=len(screenshots),
        failure=failure,
    )


def _text_assertion_failure(
    text: str,
    expected_text: Sequence[str],
    post_checks: Sequence[str],
) -> str:
    failure = ""
    missing = [value for value in expected_text if value not in text]
    if missing:
        failure = "expected text was not captured: " + ", ".join(missing)
    forbidden = [
        check.removeprefix("no_text:")
        for check in post_checks
        if check.startswith("no_text:")
    ]
    present = [value for value in forbidden if value and value in text]
    if present:
        failure = _join_failure(
            failure,
            "forbidden text was captured: " + ", ".join(present),
        )
    return failure


def _capture_remote_tmux_pane_when_ready(
    *,
    runner: capture_tool.CommandRunner,
    connection: capture_tool.LedgerHostConnection,
    pane: str,
    step: str,
    sleeper: Callable[[float], None],
    enforce_wall_clock: Callable[[str], None],
) -> str:
    text = ""
    for attempt in range(DEFAULT_CAPTURE_READY_ATTEMPTS):
        text = capture_tool.capture_remote_tmux_pane(
            key_path=connection.key_path,
            public_ip=connection.public_ip,
            ssh_user=connection.ssh_user,
            pane=pane,
            runner=runner,
        )
        if _capture_has_visible_text(text):
            return text
        if attempt + 1 < DEFAULT_CAPTURE_READY_ATTEMPTS:
            sleeper(DEFAULT_CAPTURE_READY_DELAY)
            enforce_wall_clock(f"{step} capture readiness")
    return text


def _capture_has_visible_text(text: str) -> bool:
    return bool(text.strip())


def _join_failure(existing: str, addition: str) -> str:
    if not existing:
        return addition
    if not addition:
        return existing
    return f"{existing}; {addition}"


def _normalize_max_wall_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    normalized = float(value)
    if normalized <= 0:
        return None
    return normalized


def _enforce_wall_clock(
    *,
    started_monotonic: float,
    max_wall_seconds: float | None,
    stage: str,
    clock: Callable[[], float],
) -> None:
    if max_wall_seconds is None:
        return
    elapsed = clock() - started_monotonic
    if elapsed > max_wall_seconds:
        raise TimeoutError(
            "scenario exceeded "
            f"max_wall_seconds={max_wall_seconds:g} after {stage} "
            f"(elapsed={elapsed:.1f}s)"
        )


def _remaining_command_timeout(
    *,
    default_timeout: int,
    started_monotonic: float,
    max_wall_seconds: float | None,
    clock: Callable[[], float],
) -> int:
    if max_wall_seconds is None:
        return default_timeout
    remaining = max_wall_seconds - (clock() - started_monotonic)
    return max(1, min(default_timeout, math.ceil(remaining)))


def _tmux_exit_assertion_failure(
    post_checks: Sequence[str],
    *,
    runner: capture_tool.CommandRunner,
    connection: capture_tool.LedgerHostConnection,
    pane: str,
) -> str:
    expected_codes = [
        int(check.removeprefix("tmux_exit_code:"))
        for check in post_checks
        if check.startswith("tmux_exit_code:")
    ]
    if not expected_codes:
        return ""
    status_path = _tmux_exit_status_path(pane)
    status_result = runner.run(
        ssh_argv(
            connection.key_path,
            connection.public_ip,
            f"cat {shlex.quote(status_path)} 2>/dev/null",
            ssh_user=connection.ssh_user,
        ),
        timeout=30,
    )
    status_line = (status_result.stdout or "").strip().splitlines()[-1:]
    if status_result.returncode == 0 and status_line:
        return _tmux_exit_status_code_failure(status_line[0], expected_codes)
    remote_command = (
        f"tmux display-message -p -t {shlex.quote(pane)} "
        "'#{pane_dead}:#{pane_dead_status}'"
    )
    result = runner.run(
        ssh_argv(
            connection.key_path,
            connection.public_ip,
            remote_command,
            ssh_user=connection.ssh_user,
        ),
        timeout=30,
    )
    if result.returncode != 0:
        detail = "\n".join(
            part.strip() for part in (result.stderr, result.stdout) if part.strip()
        )
        return f"tmux exit status check failed rc={result.returncode}: {detail}"
    status_line = (result.stdout or "").strip().splitlines()[-1:]
    dead, separator, raw_code = (
        status_line[0].partition(":") if status_line else ("", "", "")
    )
    if separator != ":":
        return f"tmux exit status check returned unexpected output: {result.stdout!r}"
    if dead != "1":
        return "tmux pane was still running; expected it to have exited"
    return _tmux_exit_status_code_failure(raw_code, expected_codes)


def _tmux_exit_status_code_failure(
    raw_code: str,
    expected_codes: Sequence[int],
) -> str:
    try:
        actual = int(raw_code)
    except ValueError:
        return f"tmux exit status was not an integer: {raw_code!r}"
    if actual not in expected_codes:
        expected = ", ".join(str(code) for code in expected_codes)
        return f"tmux exit status {actual} was not in expected set: {expected}"
    return ""


def _start_remote_tmux(
    *,
    runner: capture_tool.CommandRunner,
    connection: capture_tool.LedgerHostConnection,
    pane: str,
    command: str,
) -> None:
    status_path = _tmux_exit_status_path(pane)
    wrapped_script = "\n".join(
        (
            "set +e",
            command,
            "rc=$?",
            f"printf '%s\\n' \"$rc\" > {shlex.quote(status_path)}",
            "exit \"$rc\"",
        )
    )
    remote_script_path = _tmux_launch_script_path(pane)
    local_script_path = _write_local_tmux_launch_script(wrapped_script, pane)
    try:
        result = runner.run(
            scp_argv(
                connection.key_path,
                connection.public_ip,
                local_script_path,
                remote_script_path,
                ssh_user=connection.ssh_user,
            ),
            timeout=60,
        )
    finally:
        local_script_path.unlink(missing_ok=True)
    if result.returncode != 0:
        detail = "\n".join(
            part.strip() for part in (result.stderr, result.stdout) if part.strip()
        )
        raise RuntimeError(
            f"remote tmux launch script copy failed rc={result.returncode}: {detail}"
        )
    remote_command = (
        f"tmux kill-session -t {shlex.quote(pane)} >/dev/null 2>&1 || true; "
        f"rm -f {shlex.quote(status_path)}; "
        "tmux start-server; "
        "tmux set-option -g remain-on-exit on; "
        f"tmux new-session -d -s {shlex.quote(pane)} "
        f"{shlex.quote('sh ' + remote_script_path)}"
    )
    _run_ssh_action(runner, connection, remote_command)


def _write_local_tmux_launch_script(script: str, pane: str) -> Path:
    safe_pane = _safe_pane_name(pane)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix=f"yoke-live-tui-{safe_pane}-",
        suffix=".sh",
        delete=False,
    ) as handle:
        handle.write(script)
        handle.write("\n")
        return Path(handle.name)


def _tmux_launch_script_path(pane: str) -> str:
    return f"/tmp/yoke-live-tui-{_safe_pane_name(pane)}.sh"


def _tmux_exit_status_path(pane: str) -> str:
    return f"/tmp/yoke-live-tui-{_safe_pane_name(pane)}.exit"


def _safe_pane_name(pane: str) -> str:
    safe_pane = "".join(
        char if char.isalnum() or char in "._-" else "_" for char in pane
    )
    return safe_pane or "pane"


def _stop_remote_tmux(
    *,
    runner: capture_tool.CommandRunner,
    connection: capture_tool.LedgerHostConnection,
    pane: str,
) -> None:
    remote_command = f"tmux kill-session -t {shlex.quote(pane)} >/dev/null 2>&1 || true"
    _run_ssh_action(runner, connection, remote_command)


def _run_ssh_action(
    runner: capture_tool.CommandRunner,
    connection: capture_tool.LedgerHostConnection,
    command: str,
) -> None:
    result = runner.run(
        ssh_argv(
            connection.key_path,
            connection.public_ip,
            command,
            ssh_user=connection.ssh_user,
        )
    )
    if result.returncode != 0:
        detail = "\n".join(
            part.strip() for part in (result.stderr, result.stdout) if part.strip()
        )
        raise RuntimeError(
            f"remote tmux action failed rc={result.returncode}: {detail}"
        )


def _write_report(
    *,
    campaign_root: Path,
    assignment_id: str,
    scenario_id: str,
    host_id: str,
    started_at: str,
    completed_at: str,
    overall_result: str,
    captures: Sequence[dict[str, object]],
    screenshots: Sequence[dict[str, object]],
    expected_text: Sequence[str],
    post_checks: Sequence[str],
    failure: str,
    secret_free: bool,
    max_wall_seconds: float | None,
) -> Path:
    report_path = (
        campaign_root
        / "reports"
        / f"{_report_path_component(assignment_id)}-{_report_path_component(scenario_id)}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    scenario = {
        "scenario_id": scenario_id,
        "result": overall_result,
        "captures": list(captures),
        "screenshots": list(screenshots),
        "assertions": {
            "expected_text": list(expected_text),
            "post_checks": list(post_checks),
            "secret_free": secret_free,
            "max_wall_seconds": max_wall_seconds,
        },
        "failure": failure,
    }
    existing = _load_existing_report(report_path)
    scenarios = [
        item
        for item in existing.get("scenarios", [])
        if isinstance(item, dict) and item.get("scenario_id") != scenario_id
    ]
    scenarios.append(scenario)
    combined_result = (
        "fail" if any(item.get("result") != "pass" for item in scenarios) else "pass"
    )
    payload = {
        "assignment_id": assignment_id,
        "campaign_root": str(campaign_root),
        "host_id": host_id,
        "started_at": str(existing.get("started_at") or started_at),
        "completed_at": completed_at,
        "overall_result": combined_result,
        "scenarios": scenarios,
    }
    json_helper.dump_path(report_path, payload)
    return report_path


def _archive_existing_scenario_output(
    *,
    campaign_root: Path,
    assignment_id: str,
    scenario_id: str,
    archive_id: str,
) -> None:
    archive_root = (
        campaign_root / "evidence-archive" / _report_path_component(archive_id)
    )
    for evidence_kind in ("captures", "screenshots"):
        source_dir = campaign_root / evidence_kind / assignment_id / scenario_id
        if not source_dir.is_dir():
            continue
        target_dir = archive_root / evidence_kind / assignment_id / scenario_id
        for child in sorted(source_dir.iterdir()):
            if not child.is_file():
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            child.replace(target_dir / child.name)

    report_path = (
        campaign_root
        / "reports"
        / f"{_report_path_component(assignment_id)}-{_report_path_component(scenario_id)}.json"
    )
    if report_path.is_file():
        target_dir = archive_root / "reports"
        target_dir.mkdir(parents=True, exist_ok=True)
        report_path.replace(target_dir / report_path.name)


def _load_existing_report(report_path: Path) -> dict[str, object]:
    if not report_path.is_file():
        return {}
    payload = json_helper.load_path(report_path)
    if not isinstance(payload, dict):
        raise ValueError(f"report root must be a JSON object: {report_path}")
    return payload


def _report_path_component(value: str) -> str:
    component = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip()
    )
    return component or "unknown"


def _emit(payload: dict[str, object], as_json: bool, *, rc: int) -> int:
    if as_json:
        print(json_helper.dumps_pretty(payload), end="")
    else:
        print(f"{payload['overall_result']}: {payload['report_path']}")
    return rc


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
