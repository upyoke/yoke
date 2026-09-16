"""Executor canonical/display-alias packet teaching assertions.

Companion to ``test_schema_api_context_tier1.py``; split out to keep
both files under the 350-line authored cap.
"""

from __future__ import annotations

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL


def _main_body() -> str:
    return sac.render_role_packet("main_agent", detail=PACKET_DETAIL_FULL)


def test_harness_sessions_executor_canonical_only_taught() -> None:
    """``harness_sessions.executor`` is documented as canonical-only and
    the surface-specific alias lives in ``executor_surface``."""

    body = _main_body()
    assert "executor stores only the canonical harness_id enum values" in body
    assert "executor_surface" in body
    assert "canonical_harness_id" in body
