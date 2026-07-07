"""Tests for the read-only / self-orientation classifier.

The classifier returns a short label for commands that should be
allowed under Yoke Authority regardless of the session's cwd. Non-
read-only commands return ``None``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    match_read_only_signature,
)


class TestDbRouterSignatures:
    @pytest.mark.parametrize(
        "command,want_signature",
        [
            (
                'python3 -m yoke_core.cli.db_router query "SELECT 1"',
                "db_router-query",
            ),
            (
                "python3 -m yoke_core.cli.db_router events list --since '1 hour ago'",
                "db_router-events-list",
            ),
            (
                "python3 -m yoke_core.cli.db_router path-claims list --item YOK-1",
                "db_router-path-claims-list",
            ),
            (
                "python3 -m yoke_core.cli.db_router harness-sessions who-claims YOK-1",
                "db_router-harness-sessions-who-claims",
            ),
            (
                "python3 -m yoke_core.cli.db_router items get YOK-1 status",
                "db_router-items-get",
            ),
            (
                "python3 -m yoke_core.cli.db_router sections get YOK-1 'Progress Log'",
                "db_router-sections-get",
            ),
            (
                "python3 -m yoke_core.cli.db_router --help",
                "db_router-help",
            ),
        ],
    )
    def test_db_router_read_only_commands_classify(self, command, want_signature):
        assert match_read_only_signature(command) == want_signature

    def test_db_router_update_does_not_classify_as_read_only(self):
        cmd = "python3 -m yoke_core.cli.db_router items update YOK-1 status implementing"
        assert match_read_only_signature(cmd) is None


class TestServiceClientSignatures:
    @pytest.mark.parametrize(
        "command,want_signature",
        [
            (
                "python3 -m yoke_core.api.service_client --help",
                "service_client-help",
            ),
            (
                "python3 -m yoke_core.api.service_client session-checkpoint-read",
                "service_client-session-checkpoint-read",
            ),
            (
                "python3 -m yoke_core.api.service_client foo-list",
                "service_client-foo-list",
            ),
            (
                "python3 -m yoke_core.api.service_client backlog-cli-get",
                "service_client-backlog-cli-get",
            ),
            (
                "python3 -m yoke_core.api.service_client claim-conflicts",
                "service_client-claim-conflicts",
            ),
        ],
    )
    def test_service_client_read_only_commands_classify(
        self, command, want_signature
    ):
        assert match_read_only_signature(command) == want_signature

    def test_service_client_mutation_command_does_not_classify(self):
        cmd = "python3 -m yoke_core.api.service_client claim-work --item YOK-1"
        assert match_read_only_signature(cmd) is None


class TestHarnessSessionsSignatures:
    def test_who_claims_classifies(self):
        cmd = "python3 -m runtime.harness.harness_sessions who-claims YOK-1"
        assert (
            match_read_only_signature(cmd)
            == "harness_sessions-who-claims"
        )

    def test_help_classifies(self):
        assert (
            match_read_only_signature(
                "python3 -m runtime.harness.harness_sessions --help"
            )
            == "harness_sessions-help"
        )

    def test_mutation_subcommand_does_not_classify(self):
        cmd = "python3 -m runtime.harness.harness_sessions begin sess-x DARIUS anthropic opus /tmp"
        assert match_read_only_signature(cmd) is None


class TestGitSignatures:
    @pytest.mark.parametrize(
        "command,want_signature",
        [
            ("git status", "git-status"),
            ("git log --oneline", "git-log"),
            ("git diff", "git-diff"),
            ("git show HEAD", "git-show"),
            ("git rev-parse HEAD", "git-rev-parse"),
            ("git branch", "git-branch"),
        ],
    )
    def test_git_read_only_commands_classify(self, command, want_signature):
        assert match_read_only_signature(command) == want_signature

    def test_git_with_dash_C_does_not_classify(self):
        assert (
            match_read_only_signature("git -C /some/path status")
            is None
        )

    def test_git_with_git_dir_does_not_classify(self):
        assert (
            match_read_only_signature(
                "git --git-dir=/some/.git status"
            )
            is None
        )

    def test_git_mutation_does_not_classify(self):
        assert match_read_only_signature("git commit -m 'msg'") is None
        assert match_read_only_signature("git push") is None


class TestSingleArgReadSignatures:
    @pytest.mark.parametrize(
        "command,want_signature",
        [
            ("wc -l /tmp/foo", "wc-read"),
            ("ls", "ls-read"),
            ("ls /tmp", "ls-read"),
            ("cat /tmp/foo", "cat-read"),
            ("head -50 /tmp/foo", "head-read"),
            ("tail -80 /tmp/foo", "tail-read"),
        ],
    )
    def test_single_path_read_classifies(self, command, want_signature):
        assert match_read_only_signature(command) == want_signature

    def test_multi_arg_cat_does_not_classify(self):
        assert match_read_only_signature("cat /tmp/a /tmp/b") is None


class TestGrepLikeSignatures:
    @pytest.mark.parametrize(
        "command,want_signature",
        [
            ("grep -r foo .", "grep"),
            ("rg foo", "rg"),
            ("ag foo", "ag"),
        ],
    )
    def test_grep_like_classifies(self, command, want_signature):
        assert match_read_only_signature(command) == want_signature


class TestCompoundCommands:
    def test_pipe_disqualifies_classification(self):
        assert (
            match_read_only_signature("git status | head -1")
            is None
        )

    def test_semicolon_disqualifies_classification(self):
        assert (
            match_read_only_signature("git status; git log")
            is None
        )

    def test_and_disqualifies_classification(self):
        assert (
            match_read_only_signature("git status && pytest")
            is None
        )

    def test_or_disqualifies_classification(self):
        assert (
            match_read_only_signature("git status || true")
            is None
        )


class TestNonReadOnlyCommands:
    def test_pytest_does_not_classify(self):
        assert match_read_only_signature("python3 -m pytest runtime/") is None

    def test_advance_does_not_classify(self):
        assert (
            match_read_only_signature(
                "python3 -m yoke_core.engines.advance_implementation_entry --item YOK-1"
            )
            is None
        )

    def test_arbitrary_python_does_not_classify(self):
        assert (
            match_read_only_signature(
                "python3 -m yoke_core.domain.foo do-something"
            )
            is None
        )

    def test_arbitrary_python_with_help_classifies(self):
        # --help on any python -m module is read-only by definition.
        assert (
            match_read_only_signature(
                "python3 -m yoke_core.domain.foo --help"
            )
            == "python-yoke_core.domain.foo-help"
        )


class TestEdgeCases:
    def test_empty_command_returns_none(self):
        assert match_read_only_signature("") is None
        assert match_read_only_signature("   ") is None

    def test_invalid_shell_returns_none(self):
        # Unbalanced quote — shlex.split raises ValueError; classifier
        # treats it as "not classifiable" rather than crashing.
        assert match_read_only_signature("git status '") is None

    def test_env_prefix_is_stripped_before_classification(self):
        cmd = "YOKE_SESSION_ID=abc python3 -m yoke_core.cli.db_router query 'SELECT 1'"
        assert match_read_only_signature(cmd) == "db_router-query"

    def test_pythonpath_override_disqualifies_read_only_classification(self):
        """``PYTHONPATH=/not/yoke python3 -m yoke_core.cli.db_router`` must
        NOT match the read-only allow-path. The PYTHONPATH-equivalence
        check in ``lint_session_cwd_control_plane`` is the canonical
        surface for module-resolution-override commands and it operates
        on the cwd-fallback deny branch.
        """
        cmd = (
            "PYTHONPATH=/not/yoke python3 -m "
            "yoke_core.cli.db_router items get YOK-42 status"
        )
        assert match_read_only_signature(cmd) is None

    def test_pythonhome_override_disqualifies_read_only_classification(self):
        cmd = (
            "PYTHONHOME=/elsewhere python3 -m "
            "yoke_core.cli.db_router query 'SELECT 1'"
        )
        assert match_read_only_signature(cmd) is None
