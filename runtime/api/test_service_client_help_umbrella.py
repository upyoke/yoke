"""Tests for the Atlas-family grouping used by ``service_client --help``."""

from __future__ import annotations

from yoke_core.api.service_client_help_umbrella import (
    group_commands,
    render_umbrella_help,
)


def test_group_commands_routes_known_names_into_declared_families():
    commands = [
        "item-get", "claim-work", "release-work-claim",
        "path-claim-register", "path-claim-widen",
        "coordination-lease-acquire", "session-begin",
        "field-note-log",
    ]
    grouped = dict(group_commands(commands))
    assert "item-get" in grouped["Items / Backlog reads"]
    assert "claim-work" in grouped["Claims — work"]
    assert "release-work-claim" in grouped["Claims — work"]
    # Prefix match covers every path-claim-* command in one entry.
    assert "path-claim-register" in grouped["Claims — path"]
    assert "path-claim-widen" in grouped["Claims — path"]
    assert "coordination-lease-acquire" in grouped["Coordination leases"]
    assert "session-begin" in grouped["Sessions"]
    assert "field-note-log" in grouped["Ouroboros"]


def test_group_commands_other_bucket_collects_unknown_names():
    grouped = dict(group_commands(["item-get", "novel-future-command"]))
    assert grouped["Other"] == ["novel-future-command"]


def test_group_commands_no_other_bucket_when_all_classified():
    grouped = dict(group_commands(["item-get", "claim-work"]))
    assert "Other" not in grouped


def test_render_umbrella_help_includes_usage_worked_example_and_groups():
    rendered = render_umbrella_help(
        ["item-get", "claim-work", "path-claim-register"]
    )
    # Usage line + canonical entrypoint.
    assert "Usage: python3 -m yoke_core.api.service_client <command>" in rendered
    # Worked example with a concrete YOK-N (matches AC-2 canonical shape).
    assert "YOK-N" in rendered
    assert "claim-work" in rendered
    # Per-command help hint.
    assert "Run ``<command> --help``" in rendered
    # Family labels appear.
    assert "Items / Backlog reads:" in rendered
    assert "Claims — work:" in rendered
    assert "Claims — path:" in rendered


def test_render_umbrella_help_against_live_command_inventory():
    """Smoke-test: the live COMMANDS keyset should classify cleanly.

    A new unclassified subcommand surfaces as ``Other`` so authors
    notice it without breaking the build.
    """
    from yoke_core.api.service_client import COMMANDS

    rendered = render_umbrella_help(COMMANDS.keys())
    # All canonical Yoke families render at least once.
    expected_labels = (
        "Items / Backlog reads",
        "Claims — work",
        "Claims — path",
        "Sessions",
        "Project Structure",
        "Ouroboros",
    )
    for label in expected_labels:
        assert f"{label}:" in rendered, f"missing family heading: {label}"
