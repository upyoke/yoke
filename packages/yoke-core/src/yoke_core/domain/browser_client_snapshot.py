"""Snapshot primitives for ``browser_client``: accessibility / screenshot / diff.

These three thin wrappers convert their public arguments into the daemon's
``/api/snapshot/*`` request body and forward the call through
``daemon_request``.

**Parent-module patch routing.** ``test_browser_client.py`` patches
``browser_client.daemon_request`` for every snapshot test. To preserve that
contract every parent-bound symbol — ``daemon_request`` and
``_parse_viewport`` — is resolved via
``_bc = yoke_core.domain.browser_client`` at call time, never via a direct
sibling import. Importing those names directly into this module would bypass
the parent's patched names and silently break the test contract.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def snapshot_accessibility(url: str) -> Dict[str, Any]:
    """Get accessibility tree for a URL."""
    from yoke_core.domain import browser_client as _bc

    return _bc.daemon_request("/api/snapshot/accessibility", {"url": url})


def snapshot_screenshot(
    url: str,
    annotate: bool = False,
    output_path: Optional[str] = None,
    viewport: Optional[str] = None,
) -> Dict[str, Any]:
    """Capture a screenshot of a URL.

    ``viewport`` is ``WxH`` format, e.g. ``1280x720``.
    """
    from yoke_core.domain import browser_client as _bc

    body: Dict[str, Any] = {"url": url, "annotate": annotate}
    if output_path:
        body["outputPath"] = output_path
    if viewport:
        w, h = _bc._parse_viewport(viewport)
        body["viewport"] = {"width": w, "height": h}
    return _bc.daemon_request("/api/snapshot/screenshot", body)


def snapshot_diff(
    url: str,
    baseline: str,
    viewport: str,
    output_dir: Optional[str] = None,
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """Diff a URL's current state against a baseline screenshot."""
    from yoke_core.domain import browser_client as _bc

    w, h = _bc._parse_viewport(viewport)
    body: Dict[str, Any] = {
        "url": url,
        "baselinePath": baseline,
        "viewport": {"width": w, "height": h},
    }
    if output_dir:
        body["outputDir"] = output_dir
    if threshold is not None:
        body["threshold"] = threshold
    return _bc.daemon_request("/api/snapshot/diff", body)
