"""Discoverability behavior for command groups and natural spellings."""

from __future__ import annotations

import pytest

from yoke_cli.main import main


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["doctor"], "yoke doctor run"),
        (["deployments"], "yoke deployment-flows list"),
        (["worktrees"], "yoke item-worktrees list"),
        (["source"], "yoke source-authority export"),
        (["qa", "review"], "yoke qa plan review-submit"),
        (["github", "actions", "get"], "yoke github-actions check-ci"),
        (["simulate"], "/yoke simulate --system"),
    ],
)
def test_bare_and_intuitive_groups_route_to_real_surfaces(
    argv, expected, capsys
) -> None:
    assert main(argv) == 0
    assert expected in capsys.readouterr().out


def test_unknown_member_suggests_nearest_real_subcommand(capsys) -> None:
    assert main(["doctor", "rn"]) == 2
    assert "Did you mean `yoke doctor run`?" in capsys.readouterr().err


def test_space_separated_hyphenated_family_resolves(capsys) -> None:
    assert main(["github", "actions", "wait", "--help"]) == 0
    assert "yoke github-actions wait-run" in capsys.readouterr().out
