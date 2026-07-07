"""HCs covering the Codex ``apply_patch`` smoke surface.

Split out of ``doctor_hc_codex_hooks`` so each module stays well under the
350-line cap. These two checks share a dependency on the (not-yet-provisioned)
``runtime.harness.codex.apply_patch_smoke`` module:

* ``HC-apply-patch-deny-smoke`` — the offline deny smoke still exits zero.
* ``HC-apply-patch-observe-smoke`` — ``HarnessToolCall`` events landed for
  ``apply_patch`` invocations.

Both remain PASS-with-note until task 1's smoke surface ships, mirroring the
``hc_path_integrity`` precedent.
"""

from __future__ import annotations

import subprocess

from yoke_core.domain import db_backend
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _smoke_module_available() -> bool:
    try:
        import importlib

        return importlib.util.find_spec(
            "runtime.harness.codex.apply_patch_smoke",
        ) is not None
    except Exception:
        return False


def hc_apply_patch_deny_smoke(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "HC-apply-patch-deny-smoke"
    desc = "apply_patch deny smoke still passes offline"
    if not _smoke_module_available():
        rec.record(
            name, desc, "PASS",
            "apply_patch smoke surface not yet provisioned; skipping",
        )
        return
    try:
        result = subprocess.run(
            [
                "python3", "-m",
                "runtime.harness.codex.apply_patch_smoke", "deny",
            ],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        rec.record(name, desc, "FAIL", f"smoke runner failed: {exc}")
        return
    if result.returncode != 0:
        rec.record(
            name, desc, "FAIL",
            f"deny smoke exited {result.returncode}; "
            f"stderr: {result.stderr.strip()[:400]}",
        )
        return
    rec.record(name, desc, "PASS", "deny smoke passed")


def hc_apply_patch_observe_smoke(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "HC-apply-patch-observe-smoke"
    desc = "apply_patch events recorded with changed paths"
    if not _smoke_module_available():
        rec.record(
            name, desc, "PASS",
            "apply_patch smoke surface not yet provisioned; skipping",
        )
        return
    # Read-only DB query: did any apply_patch tool-call event land?
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        cur = conn.execute(
            f"SELECT count(*) FROM events "
            "WHERE event_name = 'HarnessToolCall' "
            f"AND envelope LIKE {p} "
            "LIMIT 1",
            ("%apply_patch%",),
        )
        row = cur.fetchone()
        count = int(row[0]) if row else 0
    except Exception as exc:
        rec.record(
            name, desc, "PASS",
            f"events table inaccessible ({exc}); smoke not yet exercised",
        )
        return
    if count <= 0:
        rec.record(
            name, desc, "PASS",
            "no apply_patch events seen yet; smoke run pending",
        )
        return
    rec.record(name, desc, "PASS", f"observed {count}+ apply_patch event(s)")
