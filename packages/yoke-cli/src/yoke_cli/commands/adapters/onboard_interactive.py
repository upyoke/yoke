"""Interactive launch and post-UI source activation for onboarding."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_wizard


def run_wizard(
    parsed: Any,
    env_name: str,
    selected_mode: str,
    destination: str | None,
    *,
    apply_with_report: Callable[..., dict],
    print_failure: Callable[[Any], None],
) -> int:
    defaults = onboard_wizard.WizardDefaults(
        config_path=str(machine_config.config_path(parsed.config_path)),
        env_name=env_name or None,
        api_url=parsed.api_url,
        destination=destination,
        token=parsed.token,
        token_file=parsed.token_file,
        mode=selected_mode if (parsed.quick or parsed.advanced) else None,
        project_mode=parsed.project_mode,
        project_checkout=parsed.project_checkout,
        apply=parsed.apply,
        post_install=parsed.post_install,
    )

    def apply_report(kwargs: dict, tui_progress=None) -> dict:
        if parsed.skip_identity_check:
            kwargs = {**kwargs, "check_identity": False}
        if parsed.resume_run_id:
            kwargs = {
                **kwargs,
                "resume_run_id": parsed.resume_run_id,
                "resume_payload": parsed.resume_payload,
            }
        return apply_with_report(kwargs, tui_progress=tui_progress)

    try:
        result = onboard_wizard.run_wizard(defaults, apply_report=apply_report)
    except onboard_wizard.WizardCancelled as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if result.error:
        print_failure(result)
        return 1
    if result.cancelled and result.machine_github_saved:
        print(
            "GitHub App authorization remains saved on this machine. Run "
            "`yoke github disconnect` to remove it.",
            file=sys.stderr,
        )
    finish_pending_source_install(parsed.config_path)
    return result.exit_code


def finish_pending_source_install(config_path: str | None, *, stream=None) -> None:
    """Finish the editable install only after the Textual process has closed."""
    from yoke_cli.config import dev_setup
    from yoke_cli.config import project_onboard_apply

    stream = stream or sys.stdout
    root = project_onboard_apply.pop_pending_dev_install(config_path)
    if not root:
        return
    print("\nFinalizing Yoke source activation…", file=stream)
    outcome = dev_setup.run_editable_install_step(Path(root))
    if outcome.get("ok"):
        print(f"✓ `yoke` now runs from {root}.", file=stream)
        return
    print(f"⚠ Couldn't finish source activation: {outcome.get('error')}", file=stream)
    print(
        f"  Finish it with: yoke dev setup {root} --editable-install --yes",
        file=stream,
    )


__all__ = ["finish_pending_source_install", "run_wizard"]
