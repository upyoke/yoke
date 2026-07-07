"""Apply/report adapter helpers for ``yoke onboard``."""

from __future__ import annotations

from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_apply_lock
from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_wizard
from yoke_cli.config.onboard_error_friendly import friendly_permission_error


def apply_with_durable_report(kwargs: dict, tui_progress=None) -> dict:
    report_kwargs = {
        key: value for key, value in kwargs.items()
        if key not in ("resume_run_id", "resume_payload")
    }
    if not report_kwargs.get("apply"):
        return onboard_config.build_report(**report_kwargs)

    preview_kwargs = {**report_kwargs, "apply": False, "check_identity": False}
    preview = onboard_config.build_report(**preview_kwargs)
    with onboard_apply_lock.acquire(str(kwargs.get("resume_run_id") or "")):
        return _run_locked_apply(preview, kwargs, report_kwargs, tui_progress)


def _run_locked_apply(
    preview: dict,
    kwargs: dict,
    report_kwargs: dict,
    tui_progress=None,
) -> dict:
    writer = onboard_apply_report.ApplyReportWriter.start(preview, kwargs)

    def progress(action: str, target: str, status: str) -> None:
        if status == "running":
            writer.step_started(action, target)
        elif status == "done":
            writer.step_done(action, target)
        elif status == "skipped":
            writer.step_skipped(action, target)
        if tui_progress is not None:
            tui_progress(action, target, status)

    try:
        report = onboard_config.build_report(**report_kwargs, progress=progress)
    except Exception as exc:  # noqa: BLE001
        writer.fail(exc)
        summary = writer.summary()
        raise onboard_wizard.WizardApplyError(
            str(exc),
            failed_step=summary.get("failed_step"),
            report_path=summary.get("path"),
            resume_command=summary.get("resume_command"),
        ) from exc
    writer.finish()
    report["apply_report"] = writer.summary()
    return report


def print_failure_summary(result: onboard_wizard.WizardRunResult) -> None:
    import sys

    print(f"error: {friendly_permission_error(result.error or 'onboarding failed')}",
          file=sys.stderr)
    if result.failed_step:
        print(f"failed step: {result.failed_step}", file=sys.stderr)
    if result.report_path:
        print(f"report: {result.report_path}", file=sys.stderr)
    if result.resume_command:
        print(f"resume: {result.resume_command}", file=sys.stderr)


__all__ = ["apply_with_durable_report", "print_failure_summary"]
