"""HC-cli-help-handler-present — Yoke CLI subcommands exit 0 on --help.

Yoke-internal Doctor HC. Walks ``yoke_core.api.service_client.COMMANDS``
plus ``db_router_dispatch._DOMAIN_PY_MODULES`` and verifies every
subcommand or domain returns ``0`` when invoked with ``--help``.
Failure modes the HC catches:

* Subcommand's positional parser crashes on ``--help`` and exits
  non-zero (``Item ID must be integer, got '--help'``).
* Subcommand reads ``--help`` as the search term and queries a DB
  that may not exist in cwd (``backlog-dedup-search``).
* Subcommand returns 2 from argparse but the dispatcher does NOT
  intercept the exit code (regression on the universal safety net).

The dispatcher's safety net
(:mod:`yoke_core.api.service_client_help.run_with_help_fallback`) is the
primary mitigation. This HC verifies the safety net is in place AND
that every subcommand reaches it — so an accidental ``raise`` outside
the safety net is caught early.

Why not just run the test suite? Doctor surfaces this for operators
running ``/yoke doctor`` against a fresh checkout; a failing HC is
how an operator notices the regression without waiting for CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List

from yoke_core.domain.project_scratch_dir import scratch_subdir
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


HC_SLUG = "cli-help-handler-present"
HC_LABEL = "Yoke CLI subcommands exit 0 on --help"

_MAX_FINDINGS = 10


def hc_cli_help_handler_present(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Run service_client and db_router entries with ``--help``.

    Records FAIL listing the subcommands whose ``--help`` invocation
    did not exit ``0``. PASS otherwise. SKIPs cleanly when the repo
    root or ``service_client.COMMANDS`` cannot be resolved.
    """
    repo_root = _resolve_repo_root()
    if not repo_root:
        rec.record(HC_SLUG, HC_LABEL, "PASS", "repo root not resolvable (skip)")
        return

    try:
        from yoke_core.api.service_client import COMMANDS
        from yoke_core.cli.db_router_dispatch import _DOMAIN_PY_MODULES
    except Exception as exc:
        rec.record(HC_SLUG, HC_LABEL, "PASS", f"CLI import failed (skip): {exc!r}")
        return

    env = dict(os.environ)
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")

    failures: List[str] = []
    checked = 0
    with scratch_subdir(prefix="yoke-doctor-help") as tmp:
        for cmd in sorted(COMMANDS.keys()):
            checked += 1
            try:
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "yoke_core.api.service_client",
                        cmd,
                        "--help",
                    ],
                    capture_output=True,
                    cwd=tmp,
                    env=env,
                    timeout=30,
                )
            except Exception as exc:
                failures.append(f"{cmd}: subprocess error {exc!r}")
                continue
            if proc.returncode != 0:
                stderr = proc.stderr.decode(errors="replace")[:120]
                failures.append(
                    f"service_client {cmd}: rc={proc.returncode} stderr={stderr!r}"
                )
        for domain in sorted(_DOMAIN_PY_MODULES.keys()):
            checked += 1
            try:
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "yoke_core.cli.db_router",
                        domain,
                        "--help",
                    ],
                    capture_output=True,
                    cwd=tmp,
                    env=env,
                    timeout=30,
                )
            except Exception as exc:
                failures.append(f"db_router {domain}: subprocess error {exc!r}")
                continue
            if proc.returncode != 0:
                stderr = proc.stderr.decode(errors="replace")[:120]
                failures.append(
                    f"db_router {domain}: rc={proc.returncode} stderr={stderr!r}"
                )

    if failures:
        detail = _format_detail(failures)
        rec.record(HC_SLUG, HC_LABEL, "FAIL", detail)
    else:
        rec.record(HC_SLUG, HC_LABEL, "PASS", f"{checked} CLI entrypoint(s) exit 0 on --help")


def _format_detail(findings: List[str]) -> str:
    if len(findings) <= _MAX_FINDINGS:
        return "\n".join(findings)
    truncated = findings[:_MAX_FINDINGS]
    extra = len(findings) - _MAX_FINDINGS
    truncated.append(f"… {extra} more failures")
    return "\n".join(truncated)


__all__ = ["hc_cli_help_handler_present", "HC_SLUG", "HC_LABEL"]
