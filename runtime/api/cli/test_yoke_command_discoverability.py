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
        (["environment"], "yoke projects environment create"),
        (["environments"], "yoke projects environment-settings get"),
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


@pytest.mark.parametrize("argv", [["environment"], ["environments"]])
def test_environment_terminology_lists_registration_and_settings(argv, capsys) -> None:
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "yoke projects environment create" in out
    assert "yoke projects environment-settings get" in out
    assert "yoke projects environment-settings merge" in out


def test_unknown_member_suggests_nearest_real_subcommand(capsys) -> None:
    assert main(["doctor", "rn"]) == 2
    assert "Did you mean `yoke doctor run`?" in capsys.readouterr().err


def test_unknown_top_level_suggests_hyphenated_family(capsys) -> None:
    assert main(["runs"]) == 2
    err = capsys.readouterr().err
    assert "unknown subcommand" in err
    assert "Did you mean `yoke deployment-runs`?" in err


def test_unknown_top_level_help_still_suggests_hyphenated_family(capsys) -> None:
    assert main(["runs", "--help"]) == 2
    assert "Did you mean `yoke deployment-runs`?" in capsys.readouterr().err


def test_space_separated_hyphenated_family_resolves(capsys) -> None:
    assert main(["github", "actions", "wait", "--help"]) == 0
    assert "yoke github-actions wait-run" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "adapters", "recipes"),
    [
        (
            ["qa", "evidence", "list"],
            ("yoke qa requirement list", "yoke qa run list"),
            (
                "yoke qa requirement list [--item PREFIX-N",
                "yoke qa run list [--requirement-id N]",
            ),
        ),
        (
            ["claims", "path", "survey"],
            (
                "yoke direct-workflow dash survey",
                "yoke direct-workflow conflict-survey status",
            ),
            (
                "yoke direct-workflow dash survey ITEM --path PATH",
                "yoke direct-workflow conflict-survey status ITEM",
            ),
        ),
    ],
)
def test_conceptual_cli_names_name_the_real_adapter(
    argv, adapters, recipes, capsys
) -> None:
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "unknown subcommand" in err
    assert "subcommand group." not in err
    for adapter in adapters:
        assert f"Did you mean `{adapter}`?" in err
    for recipe in recipes:
        assert recipe in err


def test_conceptual_cli_names_match_before_flags() -> None:
    from yoke_cli.conceptual_cli_names import conceptual_cli_hint

    hint = conceptual_cli_hint(["qa", "evidence", "list", "--json"])
    assert hint is not None
    assert "Did you mean `yoke qa requirement list`?" in hint


def test_messages_send_routes_to_say(capsys) -> None:
    assert main(["messages", "send", "--help"]) == 0
    out = capsys.readouterr().out
    assert "yoke say" in out
    assert "(--preview | --stdin)" in out
