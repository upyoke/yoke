"""Every ``qa_runs`` write goes through the one module that discharges replacements.

A pass recorded anywhere else would leave a failed case its declared
replacement answered still blocking the stage gate. Schema history is the
only other code that touches the table, and it records no verdicts.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WRITER = Path("packages/yoke-core/src/yoke_core/domain/qa_run_verdict_record.py")
SCHEMA_HISTORY = {
    Path("packages/yoke-core/src/yoke_core/domain/qa_schema.py"),
    Path("packages/yoke-core/src/yoke_core/domain/schema_migrations.py"),
    # Documents its own fragment builder with an illustrative statement.
    Path("packages/yoke-core/src/yoke_core/domain/sql_json.py"),
}
RAW_WRITE = re.compile(r"(INSERT\s+INTO|UPDATE)\s+qa_runs\b", re.IGNORECASE)


def test_no_source_writes_qa_runs_outside_the_verdict_writer() -> None:
    offenders = []
    for path in sorted((REPO_ROOT / "packages").glob("*/src/**/*.py")):
        relative = path.relative_to(REPO_ROOT)
        if relative == WRITER or relative in SCHEMA_HISTORY:
            continue
        if "migrations" in relative.parts:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if RAW_WRITE.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert not offenders, (
        "write qa_runs through yoke_core.domain.qa_run_verdict_record "
        "(insert_qa_run / update_qa_run) so a pass discharges its declared "
        "replacements:\n" + "\n".join(offenders)
    )
