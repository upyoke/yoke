"""Every ``yoke`` command and group has a one-line plain-language summary."""

from __future__ import annotations

from yoke_cli.commands.command_summaries import (
    SUMMARY_MAX_CHARS,
    explicit_summaries,
    summary_for,
)
from yoke_cli.commands.command_tree import discovery_routes
from yoke_cli.main import main as cli_main


def _all_nodes() -> set[tuple[str, ...]]:
    nodes: set[tuple[str, ...]] = set()
    for route in discovery_routes():
        for length in range(1, len(route) + 1):
            nodes.add(route[:length])
    return nodes


def test_every_command_and_group_has_a_summary() -> None:
    missing = sorted(" ".join(n) for n in _all_nodes() if not summary_for(n))
    assert not missing, (
        f"{len(missing)} command(s) lack a summary; add each to "
        "packages/yoke-cli/src/yoke_cli/commands/summaries/<top>.json: "
        + ", ".join(missing[:40])
    )


def test_summaries_fit_one_short_line() -> None:
    too_long = {
        " ".join(route): text
        for route, text in explicit_summaries().items()
        if len(text) > SUMMARY_MAX_CHARS or "\n" in text or not text.strip()
    }
    assert not too_long, too_long


def test_every_summary_names_a_live_command() -> None:
    stale = sorted(" ".join(r) for r in explicit_summaries() if r not in _all_nodes())
    assert not stale, f"summaries for commands that no longer exist: {stale}"


def test_leaf_help_opens_with_its_summary(capsys) -> None:
    try:
        cli_main(["charge", "schedule", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert out.splitlines()[0] == summary_for(("charge", "schedule"))
    assert out.count("yoke charge schedule [") == 1


def test_group_help_lists_child_summaries(capsys) -> None:
    cli_main(["charge", "--help"])
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"yoke charge - {summary_for(('charge',))}"
    assert summary_for(("charge", "schedule")) in out
