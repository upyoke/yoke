"""Help and refusal surfaces name the tokens they accept.

Each case here started as a field-note: an agent guessed a subcommand, a
flag value, or an item field, the CLI refused it, and nothing on the way in
or out named the valid set. The assertions are that a caller who reads the
help — or the refusal — can pick a real token without another guess.
"""

from __future__ import annotations

import pytest

from yoke_cli.commands import group_help
from yoke_cli.commands.adapters.dash import dash_evidence
from yoke_cli.commands.adapters.items import items_get
from yoke_cli.main import main as cli_main
from yoke_contracts.dash_evidence_status import (
    PASSING_VERIFICATION_STATUSES,
    is_passing,
    rejection_message,
)
from yoke_contracts.items_projection import (
    ALLOWED_GET_FIELDS,
    unknown_field_message,
)


def _help_text(adapter, argv, capsys) -> str:
    with pytest.raises(SystemExit):
        adapter(argv)
    return capsys.readouterr().out


class TestGroupHelpWhereAGroupExists:
    def test_hyphenated_group_answers_its_spaced_spelling(self, capsys):
        """`yoke github actions --help` is a group even though the
        registered token is the hyphenated `github-actions`."""
        assert cli_main(["github", "actions", "--help"]) == 0
        out = capsys.readouterr().out
        assert "yoke github actions - subcommand group." in out
        assert "yoke github-actions poll" in out

    def test_parent_group_lists_its_hyphenated_members(self, capsys):
        assert cli_main(["github", "--help"]) == 0
        out = capsys.readouterr().out
        assert "yoke github-actions poll" in out
        assert "yoke github pr create" in out

    def test_group_listing_never_repeats_one_command(self, capsys):
        assert cli_main(["github", "actions", "--help"]) == 0
        listed = [
            line.strip()
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("  yoke ")
        ]
        assert len(listed) == len(set(listed))

    def test_unknown_leaf_prints_the_real_group_members(self, capsys):
        """A guessed leaf answers with the group's actual contents, so the
        retry is a pick from a list rather than another guess."""
        assert cli_main(["sessions", "heartbeat"]) == 2
        err = capsys.readouterr().err
        assert "unknown subcommand" in err
        assert "yoke sessions - subcommand group." in err
        assert "yoke sessions checkpoint" in err

    def test_unknown_leaf_under_no_group_stays_terse(self, capsys):
        assert cli_main(["frobnicate", "widgets"]) == 2
        err = capsys.readouterr().err
        assert "unknown subcommand" in err
        assert "subcommand group." not in err


class TestGroupTeachingNamesTheRealSurface:
    def test_sessions_group_names_what_refreshes_liveness(self, capsys):
        assert cli_main(["sessions", "--help"]) == 0
        out = capsys.readouterr().out
        assert "no standalone heartbeat command" in out
        assert "yoke sessions touch" in out

    def test_connection_group_names_the_discovery_reader(self, capsys):
        assert cli_main(["connection", "--help"]) == 0
        assert "yoke env list" in capsys.readouterr().out

    def test_singular_project_group_points_at_the_plural_reader(self, capsys):
        assert cli_main(["project", "--help"]) == 0
        out = capsys.readouterr().out
        assert "yoke projects list" in out
        assert "yoke projects checkout-context" in out

    def test_sibling_group_wins_the_nearest_hint(self):
        hint = group_help.nearest_subcommand_hint(["project", "list"])
        assert hint == "Did you mean `yoke projects list`?"


class TestItemFieldNames:
    def test_help_lists_every_accepted_field(self, capsys):
        out = _help_text(items_get, ["--help"], capsys)
        for field in sorted(ALLOWED_GET_FIELDS):
            assert field in out, field

    def test_refusal_lists_every_accepted_field(self):
        message = unknown_field_message("nonesuch")
        for field in sorted(ALLOWED_GET_FIELDS):
            assert field in message, field

    @pytest.mark.parametrize(
        "token,surface",
        [
            ("detail", "yoke items detail get"),
            ("workflow", "yoke workflows item get"),
        ],
    )
    def test_refusal_redirects_a_familiar_non_column(self, token, surface):
        """The two tokens the field-notes recorded are not columns at all;
        the refusal names the surface that does answer them."""
        message = unknown_field_message(token)
        assert f"unknown items column {token!r}" in message
        assert surface in message

    def test_refusal_suggests_a_near_miss_field(self):
        assert "status" in unknown_field_message("statuss")

    def test_handler_refusal_uses_the_shared_message(self):
        from yoke_core.domain.handlers import reads

        assert reads.unknown_field_message is unknown_field_message


class TestVerificationStatusTokens:
    def test_help_lists_the_accepted_tokens(self, capsys):
        out = _help_text(dash_evidence, ["--help"], capsys)
        for token in PASSING_VERIFICATION_STATUSES:
            assert token in out, token

    def test_flag_refuses_an_unlisted_token_and_names_the_set(self, capsys):
        assert dash_evidence(["YOK-1", "--verification-status", "pass"]) == 2
        err = capsys.readouterr().err
        assert "invalid choice: 'pass'" in err
        for token in PASSING_VERIFICATION_STATUSES:
            assert token in err, token

    def test_domain_rejection_names_the_set(self):
        message = rejection_message("pass")
        assert "'pass'" in message
        for token in PASSING_VERIFICATION_STATUSES:
            assert token in message, token

    def test_accepted_tokens_are_case_folded(self):
        assert is_passing("PASSED")
        assert not is_passing("pass")

    def test_every_flag_spelling_offers_the_same_choices(self):
        """Two adapters write this evidence field; both must offer the set."""
        from yoke_core.domain.standalone_item_merge_cli import _build_parser

        merge_flag = next(
            action for action in _build_parser()._actions
            if "--verification-status" in action.option_strings
        )
        assert tuple(merge_flag.choices) == PASSING_VERIFICATION_STATUSES


class TestWatchMergeSubcommands:
    def test_help_names_every_subcommand_and_shows_merge_item(self, capsys):
        from yoke_core.tools import watch_merge

        with pytest.raises(SystemExit):
            watch_merge.main(["--help"], prog="yoke watch merge")
        out = capsys.readouterr().out
        for name in watch_merge.SUBCOMMAND_MODULES:
            assert name in out, name
        assert "yoke watch merge merge-item -- PREFIX-N" in out
