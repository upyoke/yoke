"""Run an explicit recovery sequence after a Browser case step fails."""

from __future__ import annotations

from typing import Any


def run_cleanup(
    steps: list[dict[str, Any]],
    *,
    page_id: str,
    base_url: str,
    artifact_dir: str,
) -> str:
    """Return a durable error fragment; stop when recovery itself fails."""
    from yoke_core.domain import browser_qa as _bqa

    if not steps:
        return ""
    if not page_id:
        return "cleanup_skipped:no_page;"
    for index, step in enumerate(steps):
        try:
            response = _bqa._execute_step(step, base_url, artifact_dir, page_id)
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
        else:
            data = response.get("data", response)
            failed = not response.get("success", True) or (
                isinstance(data, dict) and not data.get("success", True)
            )
            if not failed:
                continue
            error = (
                response.get("error")
                or (data.get("error") if isinstance(data, dict) else None)
                or "step_failed"
            )
        _bqa._log(f"  Cleanup step {index}: FAILED (error={error})")
        return f"cleanup_step_{index}:{error};"
    _bqa._log(f"  Cleanup: {len(steps)} step(s) completed")
    return ""
