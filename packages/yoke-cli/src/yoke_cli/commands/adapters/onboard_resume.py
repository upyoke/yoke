"""Resume and preserve-checkout helpers for ``yoke setup``."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from yoke_cli.commands.adapters import onboard_destination_args
from yoke_cli.commands.adapters import onboard_hosted_authorization as hosted_auth
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_apply_resume


@dataclass(frozen=True)
class PreparedRun:
    """Where this setup run points, after resume defaults and saved sign-in."""

    destination: str | None = None
    env_name: str = ""
    reused_connection: bool = False
    error: str | None = None


def prepare_run(parsed: argparse.Namespace) -> PreparedRun:
    """Fold a resumed run, the destination flags and a saved hosted sign-in.

    Mutates ``parsed`` the same way for the wizard, agent mode and the flag
    path, so every shell starts from the same answers.
    """
    parsed.resume_payload = None
    if parsed.resume_run_id:
        try:
            parsed.resume_payload = onboard_apply_resume.load_payload(
                parsed.resume_run_id
            )
            snapshot = onboard_apply_resume.load_snapshot(parsed.resume_run_id)
            onboard_apply_resume.apply_defaults(parsed, snapshot)
            onboard_apply_resume.restore_owned_layer_choice(parsed, parsed.resume_payload)
        except onboard_apply_resume.OnboardApplyResumeError as exc:
            return PreparedRun(error=str(exc))
    choice = onboard_destination_args.resolve_destination(parsed)
    if choice.error:
        return PreparedRun(error=choice.error)
    env_name = choice.env_name
    reused = hosted_auth.hydrate_saved(parsed, choice.destination)
    if reused:
        env_name = parsed.env_name or env_name
    return PreparedRun(choice.destination, env_name, reused)


def use_different_folder(
    run_id: str,
    *,
    confirmed: bool,
    json_mode: bool,
) -> int:
    try:
        result = onboard_apply_resume.preserve_checkout_for_new_target(
            run_id,
            confirmed=confirmed,
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


__all__ = ["PreparedRun", "prepare_run", "use_different_folder"]
