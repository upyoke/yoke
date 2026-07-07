from __future__ import annotations

import argparse
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from yoke_core.domain import runtime_settings


def _epoch_now() -> int:
    return int(time.time())


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _timing_enabled(repo_root: Path) -> bool:
    return (
        runtime_settings.get_str(
            "session_timing_enabled",
            "false",
        )
        == "true"
    )


def _retain_days(repo_root: Path) -> int:
    return runtime_settings.get_int(
        "session_timing_retain_days",
        30,
    )


def _log_dir(repo_root: Path) -> Path:
    return repo_root / "runtime" / "ouroboros" / "session-logs"


def _append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(line)


def _assignments(**values: str) -> str:
    return "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items())


def _run_enabled(repo_root: Path) -> int:
    print("true" if _timing_enabled(repo_root) else "false")
    return 0


def _run_init(repo_root: Path, script_name: str, note: str, pid: str) -> int:
    if not script_name or not _timing_enabled(repo_root):
        return 0
    logdir = _log_dir(repo_root)
    logdir.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - (_retain_days(repo_root) * 86400)
    for path in logdir.glob("*.log"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass

    epoch = _epoch_now()
    iso = _iso_now()
    log_path = logdir / f"{_file_ts()}-{script_name}-{pid}.log"
    if note:
        _append(log_path, f"{epoch} {iso} {script_name}/START [{note}]\n")
    else:
        _append(log_path, f"{epoch} {iso} {script_name}/START\n")
    print(
        _assignments(
            _TIMING_SCRIPT=script_name,
            TIMING_START=str(epoch),
            TIMING_LAST=str(epoch),
            TIMING_LOG=str(log_path),
        )
    )
    return 0


def _run_mark(step: str, note: str, timing_log: str, timing_start: str, timing_last: str, timing_script: str) -> int:
    if not timing_log or not timing_start or not timing_last or not timing_script:
        return 0
    epoch = _epoch_now()
    iso = _iso_now()
    try:
        elapsed = epoch - int(timing_last)
        total = epoch - int(timing_start)
    except ValueError:
        return 0
    line = f"{epoch} {iso} {timing_script}/{step} elapsed={elapsed}s total={total}s"
    if note:
        line += f" [{note}]"
    _append(Path(timing_log), line + "\n")
    print(_assignments(TIMING_LAST=str(epoch)))
    return 0


def _run_end(exit_code: str, timing_log: str, timing_start: str, timing_last: str, timing_script: str) -> int:
    if not timing_log or not timing_start or not timing_last or not timing_script:
        return 0
    epoch = _epoch_now()
    iso = _iso_now()
    try:
        elapsed = epoch - int(timing_last)
        total = epoch - int(timing_start)
    except ValueError:
        return 0
    _append(
        Path(timing_log),
        f"{epoch} {iso} {timing_script}/END elapsed={elapsed}s total={total}s [exit={exit_code}]\n",
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="timing-helper")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    enabled = sub.add_parser("enabled")
    enabled.add_argument("--repo-root", required=True)

    init = sub.add_parser("init")
    init.add_argument("script_name")
    init.add_argument("note", nargs="?", default="")
    init.add_argument("--repo-root", required=True)
    init.add_argument("--pid", required=True)

    mark = sub.add_parser("mark")
    mark.add_argument("step")
    mark.add_argument("note", nargs="?", default="")
    mark.add_argument("--timing-log", default="")
    mark.add_argument("--timing-start", default="")
    mark.add_argument("--timing-last", default="")
    mark.add_argument("--timing-script", default="")

    end = sub.add_parser("end")
    end.add_argument("exit_code", nargs="?", default="0")
    end.add_argument("--timing-log", default="")
    end.add_argument("--timing-start", default="")
    end.add_argument("--timing-last", default="")
    end.add_argument("--timing-script", default="")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.subcmd == "enabled":
        return _run_enabled(Path(args.repo_root))
    if args.subcmd == "init":
        return _run_init(Path(args.repo_root), args.script_name, args.note, args.pid)
    if args.subcmd == "mark":
        return _run_mark(args.step, args.note, args.timing_log, args.timing_start, args.timing_last, args.timing_script)
    if args.subcmd == "end":
        return _run_end(args.exit_code, args.timing_log, args.timing_start, args.timing_last, args.timing_script)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
