from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TimingRow:
    step: str
    elapsed: int
    cumulative: int


def parse_timing_log(path: Path) -> tuple[str, str, int | None, list[TimingRow]]:
    session_name = ""
    start_time = ""
    start_epoch: int | None = None
    total_time: int | None = None
    rows: list[TimingRow] = []

    for raw_line in path.read_text().splitlines():
        parts = raw_line.split()
        if len(parts) < 3:
            continue
        epoch_text, iso, step_full = parts[:3]
        try:
            epoch = int(epoch_text)
        except ValueError:
            continue
        if "/" not in step_full:
            continue
        script, step = step_full.split("/", 1)

        if step == "START":
            session_name = script
            start_time = iso
            start_epoch = epoch
            continue

        fields = {key: value for key, _, value in (token.partition("=") for token in parts[3:]) if key}

        if step == "END":
            total_raw = fields.get("total", "").rstrip("s")
            if total_raw:
                try:
                    total_time = int(total_raw)
                except ValueError:
                    total_time = None
            elif start_epoch is not None:
                total_time = epoch - start_epoch
            continue

        elapsed_raw = fields.get("elapsed", "").rstrip("s")
        total_raw = fields.get("total", "").rstrip("s")
        if not elapsed_raw or not total_raw:
            continue
        try:
            rows.append(TimingRow(step=step, elapsed=int(elapsed_raw), cumulative=int(total_raw)))
        except ValueError:
            continue

    if not session_name:
        raise ValueError("no START entry found in log file")
    return session_name, start_time, total_time, rows


def render_report(path: Path) -> str:
    session_name, start_time, total_time, rows = parse_timing_log(path)
    max_idx = -1
    max_elapsed = -1
    for idx, row in enumerate(rows):
        if row.elapsed > max_elapsed:
            max_elapsed = row.elapsed
            max_idx = idx

    lines = [
        f"Session: {session_name}  Started: {start_time}",
        f"{'STEP':<30} {'ELAPSED':>10} {'CUMULATIVE':>12}",
        f"{'-' * 30:<30} {'-' * 10:>10} {'-' * 12:>12}",
    ]
    for idx, row in enumerate(rows):
        marker = " <- slowest" if idx == max_idx and len(rows) > 1 else ""
        lines.append(f"{row.step:<30} {row.elapsed:>9d}s {row.cumulative:>11d}s{marker}")
    if total_time is not None:
        lines.append(f"{'':<30} {'':>10} {total_time:>11d}s")
        lines.append(f"Total: {total_time:d}s")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: timing-report.sh <log-file>", file=sys.stderr)
        raise SystemExit(1)
    log_file = Path(args[0])
    if not log_file.is_file():
        print(f"Error: file not found: {log_file}", file=sys.stderr)
        raise SystemExit(1)
    try:
        print(render_report(log_file))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
