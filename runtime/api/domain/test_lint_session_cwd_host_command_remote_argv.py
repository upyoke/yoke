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
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    extract_command_targets,
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


class TestHostCommandRecognition:
    def test_recognizes_the_invocation_in_a_chained_body(self):
        assert is_host_command(f"cd /tmp && {_SUBJECT} -- /bin/pwd")

    def test_does_not_recognize_a_sibling_qa_subcommand(self):
        assert not is_host_command("yoke qa mission review --item-id 5")

    def test_an_empty_body_is_not_a_host_command(self):
        assert not is_host_command("")
