"""Report each installed harness's machine-wide hooks on the Doctor machine.

The hooks live in each harness's user config (see
:mod:`yoke_contracts.harness_machine_hooks`). A config Yoke cannot parse
fails, because Yoke will not overwrite it and every session outside a
project then runs without registration or machine guards. Missing, stale or
untrusted hooks warn with the setup step that repairs them.
"""

from __future__ import annotations

from typing import Any

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_harness.hooks.machine_hooks import (
    STATE_INSTALLED,
    STATE_MALFORMED,
    inspect_machine_hooks,
)

SLUG = "machine-hooks"
TITLE = "Machine-wide harness hooks are installed"


def hc_machine_hooks(conn: Any, args: DoctorArgs, rec: RecordCollector) -> None:
    """One line per installed harness: installed, missing, stale, malformed, untrusted."""
    del conn, args
    results = inspect_machine_hooks()
    if not results:
        rec.record(f"HC-{SLUG}", TITLE, "PASS", "no supported harness is installed")
        return
    detail = "\n".join(f"- {result.line()}" for result in results)
    if any(result.outcome == STATE_MALFORMED for result in results):
        status = "FAIL"
    elif any(result.outcome != STATE_INSTALLED for result in results):
        status = "WARN"
    else:
        status = "PASS"
    rec.record(f"HC-{SLUG}", TITLE, status, detail)


__all__ = ["SLUG", "TITLE", "hc_machine_hooks"]
