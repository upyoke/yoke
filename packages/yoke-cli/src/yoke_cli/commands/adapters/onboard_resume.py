"""Resume and preserve-checkout helpers for ``yoke onboard``."""

from __future__ import annotations

import sys

from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_apply_resume


def use_different_folder(
    run_id: str,
    *,
    confirmed: bool,
    json_mode: bool,
) -> int:
    try:
        result = onboard_apply_resume.preserve_checkout_for_new_target(
            run_id, confirmed=confirmed,
        )
    except onboard_apply_resume.OnboardApplyResumeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if json_mode:
        print(onboard_config.dumps_json(result), end="")
    else:
        preserved = result.get("preserved_checkout_path") or "already absent"
        print("Yoke onboarding checkout preserved")
        print(f"  run: {result['run_id']}")
        print(f"  preserved checkout: {preserved}")
        print("  removed GitHub repo: no")
        print(f"  report: {result['report_path']}")
    return 0


__all__ = ["use_different_folder"]
