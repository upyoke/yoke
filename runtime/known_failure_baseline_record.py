"""Record a yoke-suite run's failures into one OS's known-failure baseline.

    python -m runtime.known_failure_baseline_record --os windows --reports DIR

``DIR`` holds the run's shard outputs: the ``pytest-output-<os>-<shard>``
artifacts or saved job logs. Every ``FAILED``/``ERROR`` line of pytest's
short test summary becomes an entry whose reason is its failure message; an
entry the plugin reported as ``[XPASS(strict)] <node id> passed`` is deleted,
and every other existing entry is kept. Read the result before committing: an
entry is a promise that the test fails there for the stated reason, and a
flaky test belongs in a fix, not in a strict baseline.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

from runtime.known_failure_baseline import BASELINE_DIR, PLATFORM_BASELINES, XPASS_MARK

#: Entries per file: each entry is one line, so a file stays inside the
#: repository's file line limit.
ENTRIES_PER_FILE = 300
REASON_CHARACTERS = 200

_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ")
_SUMMARY = re.compile(r"^(FAILED|ERROR) ((?:runtime|tests)/\S+?)(?: - (.*))?$")
_TIMEOUT = re.compile(r"^subprocess\.TimeoutExpired: Command '\[?'?([^',\]]+).*timed out after (\S+) seconds")
_XPASS = re.compile(re.escape(XPASS_MARK) + r" ((?:runtime|tests)/\S+) passed")


def reason_text(message: str) -> str:
    """The failure message as a one-line reason; a timeout names its program."""
    timeout = _TIMEOUT.match(message)
    if timeout is not None:
        program, seconds = timeout.groups()
        message = f"subprocess.TimeoutExpired: {re.split(r'[\\/]+', program)[-1]} timed out after {seconds} seconds"
    return message[:REASON_CHARACTERS].strip() or "fails with no message"


def summary_entries(lines: Iterable[str]) -> tuple[dict[str, str], set[str]]:
    """Failures by node id with their message, and node ids that XPASSed."""
    failures: dict[str, str] = {}
    passed: set[str] = set()
    for raw in lines:
        line = _TIMESTAMP.sub("", raw.rstrip("\r\n"))
        xpass = _XPASS.search(line)
        if xpass is not None:
            passed.add(xpass.group(1))
            continue
        match = _SUMMARY.match(line)
        if match is None:
            continue
        _, node_id, message = match.groups()
        message = (message or "").strip()
        failures.setdefault(node_id, reason_text(message))
    for node_id in passed:
        failures.pop(node_id, None)
    return failures, passed


def read_reports(directory: Path) -> tuple[dict[str, str], set[str]]:
    failures: dict[str, str] = {}
    passed: set[str] = set()
    for path in sorted(p for p in directory.rglob("*") if p.suffix in {".txt", ".log"}):
        found, xpassed = summary_entries(
            path.read_text(encoding="utf-8", errors="replace").splitlines()
        )
        for node_id, reason in found.items():
            failures.setdefault(node_id, reason)
        passed |= xpassed
    return failures, passed


def _group(node_id: str) -> str:
    parts = node_id.split("::", 1)[0].split("/")[:-1]
    return "-".join(parts[:3]) or "root"


def write_baseline(os_name: str, entries: dict[str, str], root: Path = BASELINE_DIR) -> list[Path]:
    """Replace *os_name*'s files with *entries*, grouped by test directory."""
    directory = root / os_name
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.json"):
        stale.unlink()
    groups: dict[str, list[str]] = defaultdict(list)
    for node_id in sorted(entries):
        groups[_group(node_id)].append(node_id)
    written = []
    for group, node_ids in sorted(groups.items()):
        chunks = [node_ids[i : i + ENTRIES_PER_FILE] for i in range(0, len(node_ids), ENTRIES_PER_FILE)]
        for index, chunk in enumerate(chunks, start=1):
            name = group if len(chunks) == 1 else f"{group}-{index}"
            path = directory / f"{name}.json"
            body = {node_id: entries[node_id] for node_id in chunk}
            path.write_text(json.dumps(body, indent=0, ensure_ascii=False) + "\n", encoding="utf-8")
            written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    from runtime.known_failure_baseline import load_baseline

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--os", required=True, choices=sorted(set(PLATFORM_BASELINES.values())))
    parser.add_argument("--reports", required=True, type=Path)
    args = parser.parse_args(argv)
    failures, passed = read_reports(args.reports)
    entries = {k: v for k, v in load_baseline(args.os).items() if k not in passed}
    added = {k: v for k, v in failures.items() if k not in entries}
    entries.update(added)
    written = write_baseline(args.os, entries)
    print(
        f"{args.os}: {len(entries)} entries in {len(written)} files "
        f"({len(added)} added, {len(passed)} removed as XPASS)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
