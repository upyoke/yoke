"""CLI standalone subjects retain explicit plan, project, and source bindings."""

from unittest.mock import patch

import pytest

from yoke_core.domain import qa_plan_execution_cli as cli


def test_manual_plan_allows_command_sha_without_branch(capsys):
    with patch.object(
        cli, "execute_plan", return_value={"state": "passed", "results": []}
    ) as run:
        assert (
            cli.run(
                [
                    "--plan",
                    "smoke",
                    "--project",
                    "yoke",
                    "--checkout-path",
                    "/tmp/proof",
                    "--expected-sha",
                    "a" * 40,
                    "--session-id",
                    "manual-session",
                ]
            )
            == 0
        )
    assert run.call_args.kwargs["public_ref"] is None
    assert run.call_args.kwargs["deployment_run_id"] is None
    assert run.call_args.kwargs["expected_sha"] == "a" * 40
    assert run.call_args.kwargs["plan"] == "smoke"


@pytest.mark.parametrize(
    "args",
    [
        ["--plan", "smoke"],
        ["--project", "yoke"],
        ["--plan", "smoke", "--project", "yoke", "--transition", "release"],
        ["--plan", "smoke", "--project", "yoke", "--stage", "qa"],
    ],
)
def test_manual_plan_invalid_subjects_refuse_before_execution(args):
    with patch.object(cli, "execute_plan") as run, pytest.raises(SystemExit):
        cli.run(args)
    run.assert_not_called()
