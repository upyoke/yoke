"""Merge wait help chooses the caller harness wake capability."""

from yoke_core.domain.standalone_item_merge_cli_parser import build_parser


def test_merge_wait_help_routes_from_harness_capability_not_executor_name():
    help_text = " ".join(build_parser().format_help().split())
    assert "Ignored for a relay-launched session" in help_text
    assert "the landing notice wakes it for close-out" in help_text
    assert "watch merge wrapper" in help_text
    assert "no or unverified idle wake gets one foreground command" in help_text
    assert "only a native idle-wake primitive may release" in help_text
    assert "Codex/Cursor" not in help_text
