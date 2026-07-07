"""Section GitHub sync uses a short budget so function calls return promptly."""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain import backlog_rendering
from yoke_core.domain import sections


def test_section_sync_uses_bounded_github_budget():
    captured: dict[str, object] = {}

    def fake_sync_body(item_id, out, **kwargs):
        captured["item_id"] = item_id
        captured.update(kwargs)
        return True, "compact"

    with patch(
        "yoke_core.domain.backlog_rendering._sync_body",
        side_effect=fake_sync_body,
    ):
        ok, reason = sections.sync_body_after_section_mutation(1902, "append")

    assert ok is True
    assert reason == ""
    assert captured == {
        "item_id": 1902,
        "github_timeout_seconds": sections.SECTION_SYNC_GITHUB_TIMEOUT_SECONDS,
        "github_max_attempts": sections.SECTION_SYNC_GITHUB_MAX_ATTEMPTS,
    }


def test_backlog_rendering_forwards_github_budget_to_sync_body():
    captured: dict[str, object] = {}

    def fake_sync_body(item_id, **kwargs):
        captured["item_id"] = item_id
        captured.update(kwargs)
        return 0

    with patch(
        "yoke_core.domain.backlog_rendering._is_dry_run",
        return_value=False,
    ), patch(
        "yoke_core.domain.backlog_github_sync.sync_body",
        side_effect=fake_sync_body,
    ), patch(
        "yoke_core.domain.db_helpers.connect",
        side_effect=RuntimeError("mode lookup should be advisory"),
    ):
        ok, mode = backlog_rendering._sync_body(
            1902,
            github_timeout_seconds=5.0,
            github_max_attempts=1,
        )

    assert ok is True
    assert mode == "full"
    assert captured["item_id"] == "1902"
    assert captured["github_timeout_seconds"] == 5.0
    assert captured["github_max_attempts"] == 1
