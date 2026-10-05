"""Capture the complete Atlas help roster inside the Doctor deadline."""

from typing import Any, Dict


def collect_help_pages_isolated(yoke_cli: Dict[str, Any]) -> Dict[str, Any]:
    """Run the complete help collector in one deadline-bound child process.

    stdout redirection is process-global, so help captures stay serial inside
    that child. The parent waits under the same Doctor deadline.
    """
    import json
    import subprocess
    import sys
    from yoke_contracts.doctor_budget import CHECK_BUDGET_S, remaining_seconds
    from yoke_core.engines.doctor_parallel_reads import bounded_read_map

    def capture(_):
        code = (
            "import json,sys; "
            "from yoke_core.tools.atlas_integrity_collect import collect_help_pages; "
            "print(json.dumps(collect_help_pages(json.load(sys.stdin))))"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                input=json.dumps(yoke_cli),
                capture_output=True,
                text=True,
                timeout=remaining_seconds(CHECK_BUDGET_S),
            )
        except subprocess.TimeoutExpired as exc:
            from yoke_contracts.doctor_budget import DoctorBudgetExhausted

            raise DoctorBudgetExhausted("doctor_check_budget_exhausted") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"Atlas help collector failed: {proc.stderr[:500]}")
        return json.loads(proc.stdout)

    return next(bounded_read_map(capture, [None]))
