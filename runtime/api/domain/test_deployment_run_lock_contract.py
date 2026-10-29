"""Source-wide contract: deployment-run locks always use the bounded owner."""

import pathlib
import re

_SOURCE_ROOT = (
    pathlib.Path(__file__).resolve().parents[3] / "packages" / "yoke-core" / "src"
)


def test_no_run_row_lock_bypasses_the_bounded_lock() -> None:
    """A raw ``FOR UPDATE`` on the run row would queue without a bound again.

    Any statement that locks ``deployment_runs`` must follow ``lock_run`` on
    the same run, so the row is already held when it executes.
    """
    offenders = []
    for path in sorted((_SOURCE_ROOT / "yoke_core").rglob("*.py")):
        if path.name == "deployment_runs_lock.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not re.search(r"FOR (NO KEY )?UPDATE", line):
                continue
            window = "\n".join(lines[max(0, index - 8) : index + 1])
            if not re.search(r"\b(?:FROM|JOIN) deployment_runs\b", window):
                continue
            if "lock_run(" not in window:
                offenders.append(f"{path.relative_to(_SOURCE_ROOT)}:{index + 1}")
    assert offenders == []
