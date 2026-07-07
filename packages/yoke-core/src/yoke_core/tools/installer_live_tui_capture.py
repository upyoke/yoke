"""Capture paired text and PNG evidence from live installer TUI sessions."""

from __future__ import annotations

import argparse
import binascii
import re
import shlex
import struct
import subprocess
import sys
import unicodedata
import zlib
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence

from yoke_core.domain import json_helper
from yoke_core.tools.installer_live_tui_fleet import DEFAULT_SSH_USER, ssh_argv


DEFAULT_PANE = "ob"
DEFAULT_SCALE = 2
DEFAULT_TIMEOUT = 30
COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}")
STEP_RE = re.compile(r"[0-9]{3}-[A-Za-z0-9][A-Za-z0-9._-]{0,120}")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> CommandResult:
        completed = subprocess.run(
            list(argv),
            env=dict(env) if env is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )


@dataclass(frozen=True)
class EvidenceCapture:
    assignment_id: str
    scenario_id: str
    step: str
    capture_path: str
    screenshot_path: str
    text_sha256: str
    screenshot_sha256: str
    text_bytes: int
    screenshot_bytes: int


@dataclass(frozen=True)
class LedgerHostConnection:
    key_path: Path
    public_ip: str
    host_id: str
    ssh_user: str


def capture_tmux_pane(
    *,
    pane: str = DEFAULT_PANE,
    history: bool = False,
    runner: CommandRunner | None = None,
) -> str:
    argv = ["tmux", "capture-pane", "-t", pane, "-p"]
    if history:
        argv.extend(["-S", "-"])
    return _run_capture(argv, runner or CommandRunner())


def capture_remote_tmux_pane(
    *,
    key_path: Path,
    public_ip: str,
    ssh_user: str = DEFAULT_SSH_USER,
    pane: str = DEFAULT_PANE,
    history: bool = False,
    runner: CommandRunner | None = None,
) -> str:
    remote_command = _tmux_capture_command(pane=pane, history=history)
    argv = ssh_argv(key_path, public_ip, remote_command, ssh_user=ssh_user)
    return _run_capture(argv, runner or CommandRunner())


def send_tmux_keys(
    *,
    pane: str,
    keys: Sequence[str],
    runner: CommandRunner | None = None,
) -> None:
    if not keys:
        raise ValueError("at least one key is required")
    _run_action(["tmux", "send-keys", "-t", pane, *keys], runner or CommandRunner())


def send_remote_tmux_keys(
    *,
    key_path: Path,
    public_ip: str,
    ssh_user: str = DEFAULT_SSH_USER,
    pane: str,
    keys: Sequence[str],
    runner: CommandRunner | None = None,
) -> None:
    if not keys:
        raise ValueError("at least one key is required")
    command = "tmux send-keys -t " + " ".join(
        [shlex.quote(pane), *(shlex.quote(key) for key in keys)]
    )
    _run_action(
        ssh_argv(key_path, public_ip, command, ssh_user=ssh_user),
        runner or CommandRunner(),
    )


def paste_remote_tmux_file(
    *,
    key_path: Path,
    public_ip: str,
    ssh_user: str = DEFAULT_SSH_USER,
    pane: str,
    file_path: str,
    runner: CommandRunner | None = None,
) -> None:
    """Paste a remote file into a tmux pane without putting contents in argv."""
    remote_command = _tmux_paste_file_command(pane=pane, file_path=file_path)
    _run_action(
        ssh_argv(key_path, public_ip, remote_command, ssh_user=ssh_user),
        runner or CommandRunner(),
    )


def _tmux_paste_file_command(*, pane: str, file_path: str) -> str:
    buffer_name = "yoke-live-input"
    script = (
        "import pathlib,subprocess,sys;"
        "data=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').strip()"
        ".encode('utf-8');"
        "subprocess.run(['tmux','load-buffer','-b',sys.argv[2],'-'],"
        "input=data,check=True);"
        "subprocess.run(['tmux','paste-buffer','-d','-b',sys.argv[2],'-t',"
        "sys.argv[3]],check=True);"
        "subprocess.run(['tmux','delete-buffer','-b',sys.argv[2]],check=False)"
    )
    return " ".join(
        [
            "python3",
            "-c",
            shlex.quote(script),
            shlex.quote(file_path),
            shlex.quote(buffer_name),
            shlex.quote(pane),
        ]
    )


def write_paired_evidence(
    *,
    campaign_root: Path,
    assignment_id: str,
    scenario_id: str,
    step: str,
    text: str,
    scale: int = DEFAULT_SCALE,
) -> EvidenceCapture:
    _validate_component("assignment_id", assignment_id)
    _validate_component("scenario_id", scenario_id)
    _validate_step(step)
    if scale < 1 or scale > 6:
        raise ValueError("scale must be between 1 and 6")

    normalized = _normalize_text(text)
    capture_path = campaign_root / "captures" / assignment_id / scenario_id / f"{step}.txt"
    screenshot_path = (
        campaign_root / "screenshots" / assignment_id / scenario_id / f"{step}.png"
    )
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    capture_path.write_text(normalized, encoding="utf-8")
    screenshot_path.write_bytes(render_text_png(normalized, scale=scale))
    screenshot_bytes = screenshot_path.read_bytes()
    text_bytes = capture_path.read_bytes()
    return EvidenceCapture(
        assignment_id=assignment_id,
        scenario_id=scenario_id,
        step=step,
        capture_path=str(capture_path),
        screenshot_path=str(screenshot_path),
        text_sha256=sha256(text_bytes).hexdigest(),
        screenshot_sha256=sha256(screenshot_bytes).hexdigest(),
        text_bytes=len(text_bytes),
        screenshot_bytes=len(screenshot_bytes),
    )


def render_text_png(text: str, *, scale: int = DEFAULT_SCALE) -> bytes:
    lines = [_display_line(line) for line in text.splitlines()] or [""]
    column_count = max(1, max(len(line) for line in lines))
    row_count = max(1, len(lines))
    char_width = 6 * scale
    char_height = 8 * scale
    margin = 8 * scale
    width = margin * 2 + column_count * char_width
    height = margin * 2 + row_count * char_height
    pixels = bytearray(_rgb(12, 14, 18) * width * height)
    foreground = _rgb(226, 232, 240)
    dim = _rgb(71, 85, 105)
    for row, line in enumerate(lines):
        for col, char in enumerate(line):
            glyph = FONT.get(char.upper(), FONT["?"])
            color = dim if char == " " else foreground
            _draw_glyph(
                pixels,
                width=width,
                x=margin + col * char_width,
                y=margin + row * char_height,
                glyph=glyph,
                color=color,
                scale=scale,
            )
    return _write_png(width, height, pixels)


def host_from_ledger(ledger_path: Path, host_id: str | None) -> tuple[Path, str, str]:
    connection = host_connection_from_ledger(ledger_path, host_id)
    return connection.key_path, connection.public_ip, connection.host_id


def host_connection_from_ledger(
    ledger_path: Path,
    host_id: str | None,
) -> LedgerHostConnection:
    ledger = json_helper.load_path(ledger_path)
    if not isinstance(ledger, dict):
        raise ValueError(f"ledger root must be a JSON object: {ledger_path}")
    hosts = [host for host in ledger.get("hosts", []) if isinstance(host, dict)]
    if not hosts:
        raise ValueError("ledger has no hosts")
    selected = hosts[0]
    if host_id is not None:
        selected = next(
            (host for host in hosts if str(host.get("host_id") or "") == host_id),
            {},
        )
        if not selected:
            raise ValueError(f"ledger has no host_id: {host_id}")
    key_path = Path(
        str(selected.get("key_path") or ledger.get("key_path") or "")
    ).expanduser()
    public_ip = str(selected.get("public_ip") or "")
    resolved_host_id = str(selected.get("host_id") or "")
    ssh_user = str(selected.get("ssh_user") or ledger.get("ssh_user") or DEFAULT_SSH_USER)
    if not key_path.is_file():
        raise ValueError(f"ledger key_path is not readable: {key_path}")
    if not public_ip:
        raise ValueError("ledger host has no public_ip")
    return LedgerHostConnection(
        key_path=key_path,
        public_ip=public_ip,
        host_id=resolved_host_id,
        ssh_user=ssh_user,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.installer_live_tui_capture",
        description="Capture live installer TUI text and matching PNG evidence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    _add_evidence_args(capture)
    capture.add_argument("--pane", default=DEFAULT_PANE)
    capture.add_argument("--history", action="store_true")
    capture.add_argument("--scale", type=int, default=DEFAULT_SCALE)
    capture.add_argument("--json", action="store_true")

    ssh_capture = subparsers.add_parser("ssh-capture")
    _add_evidence_args(ssh_capture)
    _add_ssh_args(ssh_capture)
    ssh_capture.add_argument("--pane", default=DEFAULT_PANE)
    ssh_capture.add_argument("--history", action="store_true")
    ssh_capture.add_argument("--scale", type=int, default=DEFAULT_SCALE)
    ssh_capture.add_argument("--json", action="store_true")

    file_capture = subparsers.add_parser("file-capture")
    _add_evidence_args(file_capture)
    file_capture.add_argument("--source", required=True, type=Path)
    file_capture.add_argument("--scale", type=int, default=DEFAULT_SCALE)
    file_capture.add_argument("--json", action="store_true")

    send_keys = subparsers.add_parser("send-keys")
    send_keys.add_argument("--pane", default=DEFAULT_PANE)
    send_keys.add_argument("keys", nargs="+")
    send_keys.add_argument("--json", action="store_true")

    ssh_send_keys = subparsers.add_parser("ssh-send-keys")
    _add_ssh_args(ssh_send_keys)
    ssh_send_keys.add_argument("--pane", default=DEFAULT_PANE)
    ssh_send_keys.add_argument("keys", nargs="+")
    ssh_send_keys.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            text = capture_tmux_pane(pane=args.pane, history=args.history)
            result = write_paired_evidence(
                **_evidence_kwargs(args),
                text=text,
                scale=args.scale,
            )
            return _emit_capture(result, args.json)
        if args.command == "ssh-capture":
            connection = host_connection_from_ledger(args.ledger, args.host_id)
            text = capture_remote_tmux_pane(
                key_path=connection.key_path,
                public_ip=connection.public_ip,
                ssh_user=connection.ssh_user,
                pane=args.pane,
                history=args.history,
            )
            result = write_paired_evidence(
                **_evidence_kwargs(args),
                text=text,
                scale=args.scale,
            )
            return _emit_capture(result, args.json, host_id=connection.host_id)
        if args.command == "file-capture":
            result = write_paired_evidence(
                **_evidence_kwargs(args),
                text=args.source.expanduser().read_text(encoding="utf-8"),
                scale=args.scale,
            )
            return _emit_capture(result, args.json)
        if args.command == "send-keys":
            send_tmux_keys(pane=args.pane, keys=args.keys)
            return _emit({"ok": True, "keys_sent": len(args.keys)}, args.json)
        if args.command == "ssh-send-keys":
            connection = host_connection_from_ledger(args.ledger, args.host_id)
            send_remote_tmux_keys(
                key_path=connection.key_path,
                public_ip=connection.public_ip,
                ssh_user=connection.ssh_user,
                pane=args.pane,
                keys=args.keys,
            )
            return _emit(
                {"ok": True, "host_id": connection.host_id, "keys_sent": len(args.keys)},
                args.json,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


def _add_evidence_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--campaign-root", required=True, type=Path)
    parser.add_argument("--assignment-id", required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--step", required=True)


def _add_ssh_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--host-id")


def _evidence_kwargs(args: argparse.Namespace) -> dict[str, object]:
    return {
        "campaign_root": args.campaign_root.expanduser(),
        "assignment_id": args.assignment_id,
        "scenario_id": args.scenario_id,
        "step": args.step,
    }


def _emit_capture(
    result: EvidenceCapture,
    as_json: bool,
    *,
    host_id: str | None = None,
) -> int:
    payload = {"ok": True, **asdict(result)}
    if host_id is not None:
        payload["host_id"] = host_id
    return _emit(payload, as_json)


def _emit(payload: dict[str, object], as_json: bool) -> int:
    if as_json:
        print(json_helper.dumps_pretty(payload), end="")
    else:
        print("ok")
    return 0


def _run_capture(argv: Sequence[str], runner: CommandRunner) -> str:
    result = runner.run(argv)
    if result.returncode != 0:
        raise RuntimeError(_command_error("capture command failed", result))
    return result.stdout


def _run_action(argv: Sequence[str], runner: CommandRunner) -> None:
    result = runner.run(argv)
    if result.returncode != 0:
        raise RuntimeError(_command_error("tmux command failed", result))


def _command_error(prefix: str, result: CommandResult) -> str:
    detail = "\n".join(
        part.strip() for part in (result.stderr, result.stdout) if part.strip()
    )
    return f"{prefix} rc={result.returncode}: {detail[-2000:]}"


def _tmux_capture_command(*, pane: str, history: bool) -> str:
    parts = ["tmux", "capture-pane", "-t", pane, "-p"]
    if history:
        parts.extend(["-S", "-"])
    return " ".join(shlex.quote(part) for part in parts)


def _validate_component(name: str, value: str) -> None:
    if not COMPONENT_RE.fullmatch(value):
        raise ValueError(f"{name} must be a safe path component")


def _validate_step(value: str) -> None:
    if not STEP_RE.fullmatch(value):
        raise ValueError("step must look like 000-name")


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def _display_line(line: str) -> str:
    stripped = ANSI_RE.sub("", line)
    output: list[str] = []
    for char in stripped:
        if char in {"\t", "\f", "\v"}:
            output.append(" ")
            continue
        mapped = _ascii_char(char)
        output.append(mapped)
    return "".join(output)


def _ascii_char(char: str) -> str:
    if char in FONT:
        return char
    upper = char.upper()
    if upper in FONT:
        return upper
    if unicodedata.category(char).startswith("C"):
        return " "
    replacements = {
        "\u2190": "<",
        "\u2191": "^",
        "\u2192": ">",
        "\u2193": "V",
        "\u21b5": ">",
        "\u2600": "*",
        "\u2705": "V",
        "\u2713": "V",
        "\u2714": "V",
        "\u2717": "X",
        "\u2715": "X",
        "\u2022": "*",
        "\u2014": "-",
        "\u25cf": "*",
        "\u25cb": "O",
        "\u2500": "-",
        "\u2502": "|",
        "\u2550": "=",
        "\u2551": "|",
        "\u2554": "+",
        "\u255a": "+",
        "\u256d": "+",
        "\u256e": "+",
        "\u256f": "+",
        "\u2570": "+",
        "\u2571": "/",
        "\u2572": "\\",
        "\u2573": "X",
        "\u2588": "#",
        "\u25aa": "*",
        "\u25d0": "O",
        "\u203a": ">",
        "\u00b7": ".",
        "{": "(",
        "}": ")",
        "`": "'",
    }
    if char in replacements:
        return replacements[char]
    codepoint = ord(char)
    if 0x2580 <= codepoint <= 0x259F:
        return "#"
    if 0x25A0 <= codepoint <= 0x25FF:
        return "#"
    if 0x2B00 <= codepoint <= 0x2BFF:
        return "#"
    if 0x1F300 <= codepoint <= 0x1FAFF:
        return "*"
    if unicodedata.category(char).startswith("S"):
        return "*"
    normalized = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode()
    if normalized:
        normalized_upper = normalized[0].upper()
        return normalized_upper if normalized_upper in FONT else "?"
    return "?"


def _draw_glyph(
    pixels: bytearray,
    *,
    width: int,
    x: int,
    y: int,
    glyph: tuple[str, ...],
    color: bytes,
    scale: int,
) -> None:
    for glyph_y, row in enumerate(glyph):
        for glyph_x, value in enumerate(row):
            if value != "1":
                continue
            for dy in range(scale):
                for dx in range(scale):
                    offset = ((y + glyph_y * scale + dy) * width + x + glyph_x * scale + dx) * 3
                    pixels[offset : offset + 3] = color


def _write_png(width: int, height: int, pixels: bytearray) -> bytes:
    stride = width * 3
    rows = [
        b"\x00" + bytes(pixels[y * stride : (y + 1) * stride])
        for y in range(height)
    ]
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), level=9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = binascii.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def _rgb(red: int, green: int, blue: int) -> bytes:
    return bytes((red, green, blue))


FONT: dict[str, tuple[str, ...]] = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "?": ("11110", "00001", "00010", "00100", "00100", "00000", "00100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ",": ("00000", "00000", "00000", "00000", "01100", "00100", "01000"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    ";": ("00000", "01100", "01100", "00000", "01100", "00100", "01000"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "\\": ("10000", "01000", "01000", "00100", "00010", "00010", "00001"),
    "|": ("00100", "00100", "00100", "00100", "00100", "00100", "00100"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "*": ("00000", "10101", "01110", "11111", "01110", "10101", "00000"),
    "=": ("00000", "00000", "11111", "00000", "11111", "00000", "00000"),
    "^": ("00100", "01010", "10001", "00000", "00000", "00000", "00000"),
    "~": ("00000", "00000", "01001", "10110", "00000", "00000", "00000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "[": ("01110", "01000", "01000", "01000", "01000", "01000", "01110"),
    "]": ("01110", "00010", "00010", "00010", "00010", "00010", "01110"),
    "<": ("00010", "00100", "01000", "10000", "01000", "00100", "00010"),
    ">": ("01000", "00100", "00010", "00001", "00010", "00100", "01000"),
    "'": ("00100", "00100", "01000", "00000", "00000", "00000", "00000"),
    '"': ("01010", "01010", "01010", "00000", "00000", "00000", "00000"),
    "$": ("00100", "01111", "10100", "01110", "00101", "11110", "00100"),
    "#": ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),
    "%": ("11001", "11010", "00010", "00100", "01000", "01011", "10011"),
    "&": ("01100", "10010", "10100", "01000", "10101", "10010", "01101"),
    "@": ("01110", "10001", "10111", "10101", "10111", "10000", "01110"),
}


if __name__ == "__main__":
    raise SystemExit(main())
