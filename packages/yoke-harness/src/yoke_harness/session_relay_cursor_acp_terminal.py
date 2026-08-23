"""Bounded ACP terminal client used by relay-owned Cursor turns."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import signal
import subprocess
import threading
from typing import Any, Callable, Mapping
import uuid


DEFAULT_OUTPUT_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_ARGUMENTS = 256
MAX_ARGUMENT_BYTES = 64 * 1024

ProcessFactory = Callable[..., subprocess.Popen[bytes]]


@dataclass
class _Terminal:
    process: subprocess.Popen[bytes]
    output_limit: int
    output: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    drain_thread: threading.Thread | None = None

    def append(self, chunk: bytes) -> None:
        with self.lock:
            self.output.extend(chunk)
            overflow = len(self.output) - self.output_limit
            if overflow > 0:
                del self.output[:overflow]
                self.truncated = True

    def snapshot(self) -> tuple[str, bool]:
        with self.lock:
            return self.output.decode(errors="replace"), self.truncated


def _exit_status(process: subprocess.Popen[bytes]) -> dict[str, object] | None:
    code = process.poll()
    if code is None:
        return None
    if code >= 0:
        return {"exitCode": code, "signal": None}
    try:
        name = signal.Signals(-code).name
    except ValueError:
        name = str(-code)
    return {"exitCode": None, "signal": name}


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


class CursorAcpTerminalRegistry:
    """Execute ACP terminal requests without shell expansion or unbounded capture."""

    def __init__(
        self,
        checkout: Path,
        *,
        environ: Mapping[str, str] | None = None,
        process_factory: ProcessFactory = subprocess.Popen,
    ) -> None:
        self.checkout = checkout.resolve()
        self.environ = dict(os.environ if environ is None else environ)
        self.process_factory = process_factory
        self.terminals: dict[str, _Terminal] = {}

    def _cwd(self, value: object) -> Path:
        cwd = Path(str(value)).resolve() if value else self.checkout
        if cwd != self.checkout and self.checkout not in cwd.parents:
            raise ValueError("terminal cwd is outside the checkout")
        if not cwd.is_dir():
            raise ValueError("terminal cwd is unavailable")
        return cwd

    @staticmethod
    def _command(params: dict[str, Any]) -> list[str]:
        command = params.get("command")
        args = params.get("args") or []
        if not isinstance(command, str) or not command or "\x00" in command:
            raise ValueError("terminal command is invalid")
        if not isinstance(args, list) or len(args) > MAX_ARGUMENTS:
            raise ValueError("terminal arguments are invalid")
        rendered = [command]
        for value in args:
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError("terminal argument is invalid")
            rendered.append(value)
        if sum(len(value.encode()) for value in rendered) > MAX_ARGUMENT_BYTES:
            raise ValueError("terminal command is too large")
        return rendered

    def _environment(self, params: dict[str, Any]) -> dict[str, str]:
        result = dict(self.environ)
        values = params.get("env") or []
        if not isinstance(values, list) or len(values) > MAX_ARGUMENTS:
            raise ValueError("terminal environment is invalid")
        for item in values:
            if not isinstance(item, dict):
                raise ValueError("terminal environment is invalid")
            name, value = item.get("name"), item.get("value")
            if (
                not isinstance(name, str)
                or not name
                or "=" in name
                or "\x00" in name
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise ValueError("terminal environment is invalid")
            result[name] = value
        return result

    def create(self, params: dict[str, Any]) -> dict[str, object]:
        requested_limit = params.get("outputByteLimit")
        limit = (
            int(requested_limit)
            if isinstance(requested_limit, int) and requested_limit > 0
            else DEFAULT_OUTPUT_BYTES
        )
        limit = min(limit, MAX_OUTPUT_BYTES)
        process = self.process_factory(
            self._command(params),
            cwd=self._cwd(params.get("cwd")),
            env=self._environment(params),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if process.stdout is None:
            process.terminate()
            raise ValueError("terminal output pipe unavailable")
        terminal_id = str(uuid.uuid4())
        terminal = _Terminal(process, limit)

        def drain() -> None:
            try:
                while chunk := process.stdout.read(65_536):
                    terminal.append(chunk)
                process.wait()
            except (OSError, subprocess.SubprocessError):
                pass

        thread = threading.Thread(
            target=drain,
            daemon=False,
            name="yoke-cursor-acp-terminal",
        )
        terminal.drain_thread = thread
        self.terminals[terminal_id] = terminal
        thread.start()
        return {"terminalId": terminal_id}

    def _terminal(self, params: dict[str, Any]) -> _Terminal:
        terminal_id = params.get("terminalId")
        terminal = self.terminals.get(str(terminal_id or ""))
        if terminal is None:
            raise ValueError("terminal id is unknown")
        return terminal

    def output(self, params: dict[str, Any]) -> dict[str, object]:
        terminal = self._terminal(params)
        output, truncated = terminal.snapshot()
        return {
            "output": output,
            "truncated": truncated,
            "exitStatus": _exit_status(terminal.process),
        }

    def wait_for_exit(self, params: dict[str, Any]) -> dict[str, object]:
        terminal = self._terminal(params)
        terminal.process.wait()
        if terminal.drain_thread is not None:
            terminal.drain_thread.join()
        return _exit_status(terminal.process) or {"exitCode": None, "signal": None}

    def kill(self, params: dict[str, Any]) -> dict[str, object]:
        terminal = self._terminal(params)
        if terminal.process.poll() is None:
            terminal.process.terminate()
        return {}

    def release(self, params: dict[str, Any]) -> dict[str, object]:
        terminal_id = str(params.get("terminalId") or "")
        terminal = self._terminal(params)
        _stop(terminal.process)
        if terminal.drain_thread is not None:
            terminal.drain_thread.join(timeout=2)
        self.terminals.pop(terminal_id, None)
        return {}

    def close(self) -> None:
        for terminal_id in list(self.terminals):
            try:
                self.release({"terminalId": terminal_id})
            except (OSError, subprocess.SubprocessError, ValueError):
                pass


def respond_to_agent_request(
    registry: CursorAcpTerminalRegistry,
    payload: dict[str, Any],
) -> dict[str, object]:
    """Return one ACP response while honoring the agent's allow-once option."""
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params")
    values = params if isinstance(params, dict) else {}
    try:
        if method == "session/request_permission":
            options = values.get("options")
            selected = (
                next(
                    (
                        option.get("optionId")
                        for option in options
                        if isinstance(option, dict)
                        and option.get("kind") == "allow_once"
                        and isinstance(option.get("optionId"), str)
                    ),
                    None,
                )
                if isinstance(options, list)
                else None
            )
            outcome: dict[str, object] = (
                {"outcome": "selected", "optionId": selected}
                if selected
                else {"outcome": "cancelled"}
            )
            result: dict[str, object] = {"outcome": outcome}
        elif method == "terminal/create":
            result = registry.create(values)
        elif method == "terminal/output":
            result = registry.output(values)
        elif method == "terminal/wait_for_exit":
            result = registry.wait_for_exit(values)
        elif method == "terminal/kill":
            result = registry.kill(values)
        elif method == "terminal/release":
            result = registry.release(values)
        elif method in {"cursor/ask_question", "cursor/create_plan"}:
            result = {"outcome": {"outcome": "cancelled"}}
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "unsupported request"},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32602, "message": "request refused"},
        }


__all__ = ["CursorAcpTerminalRegistry", "respond_to_agent_request"]
