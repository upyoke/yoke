"""Step execution and screenshot actions for the Browser QA daemon client."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _client():
    # Preserve the parent module's daemon_request patch seam for callers and
    # tests while keeping action construction out of the lifecycle module.
    from yoke_harness import browser_client

    return browser_client


def execute_step(
    step_json: Dict[str, Any],
    base_url: str,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"step": step_json, "baseUrl": base_url}
    if output_dir:
        body["outputDir"] = output_dir
    return _client().daemon_request("/api/exec/step", body)


def parse_viewport(viewport: str) -> tuple[int, int]:
    parts = viewport.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid viewport format: {viewport!r} (expected WxH)")
    return int(parts[0]), int(parts[1])


def snapshot_screenshot(
    url: str,
    annotate: bool = False,
    output_path: Optional[str] = None,
    viewport: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"url": url, "annotate": annotate}
    if output_path:
        body["outputPath"] = output_path
    if viewport:
        width, height = parse_viewport(viewport)
        body["viewport"] = {"width": width, "height": height}
    return _client().daemon_request("/api/snapshot/screenshot", body)


__all__ = ["execute_step", "parse_viewport", "snapshot_screenshot"]
