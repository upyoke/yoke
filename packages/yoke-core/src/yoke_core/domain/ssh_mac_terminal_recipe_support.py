"""Bounded staging, input, capture, and assertion helpers for terminal recipes."""

from __future__ import annotations

from pathlib import Path
import shlex
import time
from typing import Any, Callable, Mapping, Sequence

from yoke_core.domain.host_control_runner import HostActionResult
from yoke_core.domain.machine_qa_recipe_contracts import (
    REGISTERED_STAGE_URLS,
)
from yoke_cli.resilient_fetch import FetchError, fetch_bytes
from yoke_core.domain.ssh_mac_terminal_capture import RunRemote


UploadBytes = Callable[[str, bytes], bool]
_CAPTURE_ATTEMPTS = 20
_CAPTURE_DELAY_SECONDS = 0.25
KEY_SEQUENCE_DELAY_SECONDS = 0.2
_KEY_BYTES = {
    "C-c": "\x03",
    "C-j": "\n",
    "C-u": "\x15",
    "Down": "\x1b[B",
    "Enter": "\n",
    "Escape": "\x1b",
    "Space": " ",
    "Up": "\x1b[A",
}


def stage_recipe_files(
    files: Sequence[Mapping[str, str]],
    *,
    upload_bytes: UploadBytes,
) -> tuple[bool, list[dict[str, str]], tuple[str, ...]]:
    evidence: list[dict[str, str]] = []
    sensitive_values: list[str] = []
    for staged in files:
        remote_path = str(staged["remote_path"])
        if "source_path" in staged:
            source = Path(str(staged["source_path"])).expanduser()
            if not source.is_file():
                return False, evidence, tuple(sensitive_values)
            try:
                content = source.read_bytes()
            except OSError:
                return False, evidence, tuple(sensitive_values)
            try:
                decoded = content.decode("utf-8")
            except UnicodeDecodeError:
                decoded = ""
            sensitive_values.extend(
                value
                for value in (decoded, decoded.strip())
                if value and value not in sensitive_values
            )
            source_kind = "local_file"
        else:
            source_url = str(staged["source_url"])
            if source_url not in REGISTERED_STAGE_URLS:
                return False, evidence, tuple(sensitive_values)
            try:
                content = fetch_bytes(source_url, timeout=60).body
            except FetchError:
                return False, evidence, tuple(sensitive_values)
            source_kind = "registered_url"
        if not upload_bytes(remote_path, content):
            return False, evidence, tuple(sensitive_values)
        evidence.append(
            {
                "remote_path": remote_path,
                "source_kind": source_kind,
            }
        )
    return True, evidence, tuple(sensitive_values)


def cleanup_staged_files(
    run: RunRemote,
    staged: Sequence[Mapping[str, str]],
) -> bool:
    """Remove every successfully staged remote file after one case."""
    paths = [str(value["remote_path"]) for value in staged]
    if not paths:
        return True
    command = "rm -f " + " ".join(shlex.quote(path) for path in paths)
    return run(command, timeout=10).returncode == 0


def _screen_stuff(
    run: RunRemote,
    *,
    session: str,
    value: str,
) -> bool:
    command = f"screen -S {shlex.quote(session)} -p 0 -X stuff " + shlex.quote(value)
    return run(command, timeout=10).returncode == 0


def _paste_file(
    run: RunRemote,
    *,
    backend: str,
    session: str,
    path: str,
) -> bool:
    if not path.startswith("/"):
        return False
    if backend == "tmux":
        command = (
            f"tmux load-buffer -b yoke-qa-input {shlex.quote(path)} && "
            f"tmux paste-buffer -d -b yoke-qa-input "
            f"-t {shlex.quote(session)}"
        )
    else:
        command = (
            f"screen -S {shlex.quote(session)} -X readbuf "
            f"{shlex.quote(path)} && "
            f"screen -S {shlex.quote(session)} -p 0 -X paste ."
        )
    return run(command, timeout=10).returncode == 0


def send_recipe_keys(
    run: RunRemote,
    *,
    backend: str,
    session: str,
    keys: Sequence[str],
) -> bool:
    for index, key in enumerate(keys):
        if key.startswith("paste_file:"):
            if not _paste_file(
                run,
                backend=backend,
                session=session,
                path=key.removeprefix("paste_file:"),
            ):
                return False
        else:
            if backend == "tmux":
                command = f"tmux send-keys -t {shlex.quote(session)} " + shlex.quote(
                    key
                )
                ok = run(command, timeout=10).returncode == 0
            else:
                ok = _screen_stuff(
                    run,
                    session=session,
                    value=_KEY_BYTES.get(key, key),
                )
            if not ok:
                return False
        if index + 1 < len(keys):
            time.sleep(KEY_SEQUENCE_DELAY_SECONDS)
    return True


def capture_recipe_transcript(
    run: RunRemote,
    *,
    backend: str,
    session: str,
) -> str:
    if backend == "tmux":
        command = f"tmux capture-pane -t {shlex.quote(session)} -p -S -"
    else:
        remote = f"/tmp/{session}-transcript.txt"
        command = (
            f"screen -S {shlex.quote(session)} -p 0 -X hardcopy -h "
            f"{shlex.quote(remote)}; "
            f"cat {shlex.quote(remote)} 2>/dev/null; "
            f"rm -f {shlex.quote(remote)}"
        )
    transcript = ""
    for attempt in range(_CAPTURE_ATTEMPTS):
        result = run(command, timeout=10)
        transcript = result.stdout.replace("\x00", "") if result.returncode == 0 else ""
        if transcript.strip():
            break
        if attempt + 1 < _CAPTURE_ATTEMPTS:
            time.sleep(_CAPTURE_DELAY_SECONDS)
    return transcript


def recipe_assertion_failures(
    text: str,
    *,
    expected_text: Sequence[str],
    post_checks: Sequence[str],
    secret_values: Sequence[str],
    terminal_exit_code: int | None,
) -> list[str]:
    failures = [
        f"missing expected text: {value}"
        for value in expected_text
        if value not in text
    ]
    for check in post_checks:
        if check == "secret_free":
            if any(secret and secret in text for secret in secret_values):
                failures.append("secret value appeared in captured evidence")
        elif check.startswith("no_text:"):
            forbidden = check.removeprefix("no_text:")
            if forbidden in text:
                failures.append(f"forbidden text appeared: {forbidden}")
        elif check.startswith("terminal_exit_code:"):
            expected = int(check.removeprefix("terminal_exit_code:"))
            if terminal_exit_code != expected:
                failures.append(
                    f"terminal exit code {terminal_exit_code!r} != {expected}"
                )
    return failures


def read_recipe_exit_code(
    run: RunRemote,
    *,
    status_path: str,
) -> int | None:
    result = run(
        f"cat {shlex.quote(status_path)} 2>/dev/null",
        timeout=10,
    )
    raw = result.stdout.strip()
    if result.returncode or not raw:
        return None
    try:
        return int(raw.splitlines()[-1])
    except ValueError:
        return None


def run_command_recipe(
    run: RunRemote,
    *,
    entry_surface: str,
    config: Mapping[str, Any],
    staged: list[dict[str, str]],
    secret_values: Sequence[str],
) -> HostActionResult:
    result = run(
        entry_surface,
        timeout=max(1, int(float(config["max_wall_seconds"]))),
    )
    text = "\n".join(value for value in (result.stdout, result.stderr) if value)
    failures = recipe_assertion_failures(
        text,
        expected_text=config["expected_text"],
        post_checks=config["post_checks"],
        secret_values=secret_values,
        terminal_exit_code=result.returncode,
    )
    if result.returncode not in set(config["expected_return_codes"]):
        failures.append(f"return code {result.returncode} not in expected set")
    evidence = {
        "execution_mode": "ssh-command",
        "exit_code": result.returncode,
        "staged_files": staged,
        "steps": [
            {
                "key": str(config["actions"][0]["step"]),
                "reached": True,
                "transcript": text,
            }
        ],
        "assertion_failures": failures,
    }
    return HostActionResult(
        not failures,
        evidence,
        None if not failures else "terminal_recipe_assertion_failed",
    )


__all__ = [
    "UploadBytes",
    "capture_recipe_transcript",
    "cleanup_staged_files",
    "read_recipe_exit_code",
    "recipe_assertion_failures",
    "run_command_recipe",
    "send_recipe_keys",
    "stage_recipe_files",
]
