"""``yoke qa mission host-command`` argv runs remotely, not on this disk.

The command ships everything after its ``--`` separator over an awaiting
mission execution's retained Test Machine lease. Reading those operands
as local write targets refused ``-- /bin/ls /Users/testy`` while letting
path-free ``-- /bin/pwd`` through, which left the mission instrument
usable only for commands that mention no path at all.
"""

from __future__ import annotations

from yoke_core.domain.lint_session_cwd_control_plane import (
    build_scope_mismatch_block,
)
from yoke_core.domain.lint_session_cwd_host_command import (
    EXEMPTION_NOTE,
    is_host_command,
    remote_argv_indexes,
)
from yoke_core.domain.lint_session_cwd_denial import build_denial_reason
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    extract_command_targets,
)
from yoke_core.domain.lint_session_cwd_validate import ValidationVerdict
from yoke_core.domain.lint_session_cwd_wrapped_remote_argv import (
    wrapped_remote_argv_note,
)


_SUBJECT = (
    "yoke qa mission host-command --item-id 5 --execution-id exec-1 --requirement-id 7"
)


class TestRemoteArgvIsNotALocalWriteTarget:
    """The two invocations the clean-room mission saw refused now pass."""

    def test_home_directory_listing_extracts_no_local_target(self):
        assert extract_command_targets(f"{_SUBJECT} -- /bin/ls /Users/testy") == []

    def test_applications_listing_extracts_no_local_target(self):
        assert extract_command_targets(f"{_SUBJECT} -- /bin/ls /Applications") == []

    def test_path_free_argv_still_extracts_nothing(self):
        assert extract_command_targets(f"{_SUBJECT} -- /bin/pwd") == []

    def test_global_env_flag_does_not_hide_the_subcommand(self):
        command = (
            "yoke --env stage qa mission host-command --item YOK-1 "
            "--execution-id exec-1 --requirement-id 7 -- /bin/ls /Users/testy"
        )
        assert extract_command_targets(command) == []

    def test_gui_session_flag_before_the_separator_is_covered(self):
        command = f"{_SUBJECT} --gui-session -- /usr/sbin/screencapture /tmp/shot.png"
        assert extract_command_targets(command) == []

    def test_remote_path_after_the_gui_session_separator_is_remote(self):
        golden = "/Users/Shared/yoke-golden/testy-home-20261002"
        command = f"{_SUBJECT} --gui-session -- /bin/ls {golden}"
        assert extract_command_targets(command) == []


class TestLocalWriteTargetsStayEnforced:
    """Only the remote argv is exempt; the local portion is unchanged."""

    def test_redirect_on_the_same_segment_is_still_a_local_write(self):
        command = f"{_SUBJECT} -- /bin/ls /Users/testy > /Users/dev/out.txt"
        assert extract_command_targets(command) == ["/Users/dev/out.txt"]

    def test_a_chained_local_command_keeps_its_own_targets(self):
        command = f"{_SUBJECT} -- /bin/ls /Users/testy && ls /Users/dev/repo"
        assert extract_command_targets(command) == ["/Users/dev/repo"]

    def test_a_different_yoke_subcommand_keeps_full_extraction(self):
        command = "yoke qa case run --requirement-id 3 /Users/dev/thing"
        assert extract_command_targets(command) == ["/Users/dev/thing"]

    def test_aws_exec_local_copy_source_is_unchanged(self):
        command = (
            "yoke aws exec -- s3 cp /Users/dev/archive.json s3://example/archive.json"
        )
        assert extract_command_targets(command) == ["/Users/dev/archive.json"]

    def test_aws_logs_tail_resource_is_unchanged(self):
        command = (
            "yoke aws exec --project platform -- logs tail /yoke/stage/core --since 10m"
        )
        assert extract_command_targets(command) == []

    def test_aws_global_region_flag_still_classifies_logs(self):
        command = (
            "aws --region us-east-1 logs filter-log-events "
            "--log-group-name /yoke/prod/core"
        )
        assert extract_command_targets(command) == []

    def test_log_group_file_param_is_a_local_path(self):
        assert extract_command_targets(
            "aws logs start-query --log-group-name file:///tmp/group.txt"
        ) == ["/tmp/group.txt"]
        assert extract_command_targets(
            "aws logs start-query --log-group-name=fileb:///tmp/group.txt"
        ) == ["/tmp/group.txt"]

    def test_misplaced_log_group_flag_on_s3_stays_a_path(self):
        assert extract_command_targets(
            "aws s3 cp --log-group-name /yoke/prod/core /Users/dev/a.json "
            "s3://example/x"
        ) == ["/yoke/prod/core", "/Users/dev/a.json"]


class TestRemoteArgvIndexes:
    """The index set names exactly the tokens shipped over the lease."""

    def test_indexes_cover_every_token_after_the_separator(self):
        tokens = ["yoke", "qa", "mission", "host-command", "--", "/bin/ls", "/x"]
        assert remote_argv_indexes("yoke", tokens) == {5, 6}

    def test_a_host_command_without_a_separator_exempts_nothing(self):
        tokens = ["yoke", "qa", "mission", "host-command", "--item-id", "5"]
        assert remote_argv_indexes("yoke", tokens) == set()

    def test_a_non_yoke_command_exempts_nothing(self):
        tokens = ["ssh", "qa", "mission", "host-command", "--", "/bin/ls"]
        assert remote_argv_indexes("ssh", tokens) == set()


class TestDenialNamesTheExemption:
    """A host-command call refused anyway says why the exemption missed."""

    def test_refused_host_command_denial_names_the_exemption(self):
        body = build_scope_mismatch_block(
            offending_target="/Users/dev/out.txt",
            claims=(),
            repo_roots=("/Users/dev/repo",),
            command=f"{_SUBJECT} -- /bin/ls /Users/testy > /Users/dev/out.txt",
        )
        assert EXEMPTION_NOTE in body
        assert "host-command remote-argv exemption" in body
        assert "/Users/dev/out.txt" in body

    def test_an_unrelated_denial_carries_no_exemption_clause(self):
        body = build_scope_mismatch_block(
            offending_target="/Users/dev/out.txt",
            claims=(),
            repo_roots=("/Users/dev/repo",),
            command="echo hi > /Users/dev/out.txt",
        )
        assert "host-command remote-argv exemption" not in body

    def test_the_orientation_render_passes_no_command(self):
        body = build_scope_mismatch_block(
            offending_target="/Users/dev/elsewhere",
            claims=(),
            repo_roots=("/Users/dev/repo",),
        )
        assert "host-command remote-argv exemption" not in body


_ROLLOUT = "/Users/testy/.codex/sessions/2026/10/20/rollout-1.jsonl"


class TestPullAFileFromTheTestMachine:
    """The supported pull step is a direct host-command call."""

    def test_direct_read_of_a_test_machine_path_extracts_no_target(self):
        assert extract_command_targets(f"{_SUBJECT} -- /bin/cat {_ROLLOUT}") == []

    def test_pull_step_extracts_only_its_local_redirect(self):
        command = f"{_SUBJECT} -- base64 -i {_ROLLOUT} > /tmp/rollout.json"
        assert extract_command_targets(command) == ["/tmp/rollout.json"]


class TestWrappedRemoteArgvHint:
    """A wrapper script hides remote argv; the refusal names the direct call."""

    WRAPPED = f"bash /tmp/walk/pull.sh {_ROLLOUT}"

    def _reason(self, command: str, target: str = _ROLLOUT) -> str:
        verdict = ValidationVerdict(allow=False, offending_target=target)
        reason, _authority = build_denial_reason(
            verdict,
            {"tool_name": "Bash", "tool_input": {"command": command}},
            has_targets=True,
            command=command,
            read_only=False,
            machine_home="/Users/dev",
        )
        return reason

    def test_wrapped_call_names_the_direct_host_command_and_pull_step(self):
        reason = self._reason(self.WRAPPED)
        assert "Call host-command directly" in reason
        assert "wrapper script hides the argv" in reason
        assert "-- base64 -i REMOTE_PATH > LOCAL.json" in reason

    def test_a_call_with_a_yoke_invocation_gets_no_wrapper_hint(self):
        command = f"{_SUBJECT} -- /bin/ls /Users/testy > {_ROLLOUT}"
        assert wrapped_remote_argv_note(command, _ROLLOUT, "/Users/dev") == ""

    def test_own_home_and_shared_targets_get_no_wrapper_hint(self):
        own = "/Users/dev/notes.txt"
        shared = "/Users/Shared/yoke-golden/x"
        assert wrapped_remote_argv_note(f"cp a {own}", own, "/Users/dev") == ""
        assert wrapped_remote_argv_note(f"cp a {shared}", shared, "/Users/dev") == ""

    def test_linux_other_user_home_gets_the_hint(self):
        target = "/home/yoketest/.codex/sessions/x.jsonl"
        note = wrapped_remote_argv_note(f"sh pull.sh {target}", target, "/home/dev")
        assert "Call host-command directly" in note


class TestHostCommandRecognition:
    def test_recognizes_the_invocation_in_a_chained_body(self):
        assert is_host_command(f"cd /tmp && {_SUBJECT} -- /bin/pwd")

    def test_does_not_recognize_a_sibling_qa_subcommand(self):
        assert not is_host_command("yoke qa mission review --item-id 5")

    def test_an_empty_body_is_not_a_host_command(self):
        assert not is_host_command("")


_FLEET = "/yoke/github-actions-runner-fleet"
_FLEET_STATE = f"{_FLEET}/lifecycle-state"


class TestSsmParameterNamesAreRemoteResources:
    """SSM parameter names and paths are provider identifiers, not files."""

    def test_get_parameters_names_are_not_filesystem_targets(self):
        assert (
            extract_command_targets(
                "yoke aws exec --project platform -- ssm get-parameters "
                f"--names {_FLEET_STATE}"
            )
            == []
        )

    def test_get_parameters_by_path_is_not_a_filesystem_target(self):
        assert (
            extract_command_targets(
                "yoke aws exec --project platform -- ssm get-parameters-by-path "
                f"--path {_FLEET}"
            )
            == []
        )

    def test_several_names_and_equals_forms_are_remote(self):
        assert (
            extract_command_targets(
                f"aws ssm get-parameters --names {_FLEET_STATE} {_FLEET}/desired-count"
            )
            == []
        )
        assert (
            extract_command_targets(f"aws ssm get-parameter --name={_FLEET_STATE}")
            == []
        )
        assert (
            extract_command_targets(
                "yoke aws exec -- ssm get-parameters-by-path "
                f"--path={_FLEET} --recursive"
            )
            == []
        )
        assert (
            extract_command_targets(
                f"aws --region us-east-1 ssm get-parameter --name {_FLEET_STATE}"
            )
            == []
        )

    def test_file_param_and_local_redirect_stay_targets(self):
        assert extract_command_targets(
            "aws ssm get-parameter --name file:///tmp/parameter-name.txt"
        ) == ["/tmp/parameter-name.txt"]
        assert extract_command_targets(
            "aws ssm get-parameter --name=fileb:///tmp/parameter-name.txt"
        ) == ["/tmp/parameter-name.txt"]
        destination = "/Users/dev/out.json"
        assert extract_command_targets(
            "yoke aws exec --project platform -- ssm get-parameters "
            f"--names {_FLEET_STATE} > {destination}"
        ) == [destination]

    def test_misplaced_parameter_flag_on_s3_stays_a_path(self):
        local = "/Users/dev/a.json"
        assert extract_command_targets(
            f"aws s3 cp --path {_FLEET} {local} s3://example/x"
        ) == [_FLEET, local]
        assert extract_command_targets(
            f"aws s3 cp --name={_FLEET_STATE} {local} s3://example/x"
        ) == [_FLEET_STATE, local]

    def test_one_file_load_among_names_stays_local(self):
        assert extract_command_targets(
            "aws ssm get-parameters --names "
            f"file:///tmp/parameter-name.txt {_FLEET_STATE}"
        ) == ["/tmp/parameter-name.txt"]
