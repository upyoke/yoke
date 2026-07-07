"""Resume/start-over command helpers for ``yoke onboard``."""

from __future__ import annotations

import sys

from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_apply_resume


def start_over(run_id: str, *, confirmed: bool, json_mode: bool) -> int:
    try:
        result = onboard_apply_resume.start_over(run_id, confirmed=confirmed)
    except onboard_apply_resume.OnboardApplyResumeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if json_mode:
        print(onboard_config.dumps_json(result), end="")
    else:
        removed = "yes" if result["removed_checkout"] else "already absent"
        print("Yoke onboarding start-over")
        print(f"  run: {result['run_id']}")
        print(f"  removed checkout: {removed}")
        print("  removed GitHub repo: no")
        print(f"  report: {result['report_path']}")
    return 0


__all__ = ["start_over"]
