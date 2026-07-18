"""CLI argument-parsing tests for github_actions.

Subcommand-logic tests (poll, wait-run, find-run, check-ci, failed-log) live
in test_github_actions.py.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import github_actions


class TestCli:
    def test_poll_args(self):
        with mock.patch.object(github_actions, "cmd_poll") as m:
            try:
                github_actions.main([
                    "poll", "o/r", "123", "--project", "externalwebapp",
                ])
            except SystemExit:
                pass
            m.assert_called_once_with("o/r", "123", project="externalwebapp")

    def test_find_run_args(self):
        with mock.patch.object(github_actions, "cmd_find_run") as m:
            try:
                github_actions.main([
                    "find-run", "o/r", "ci.yml", "abc",
                    "--project", "externalwebapp",
                ])
            except SystemExit:
                pass
            m.assert_called_once_with(
                "o/r", "ci.yml", "abc", project="externalwebapp",
            )

    def test_wait_run_args(self):
        with mock.patch.object(github_actions, "cmd_wait_run") as m:
            try:
                github_actions.main([
                    "wait-run", "o/r", "123", "--timeout", "42",
                    "--project", "externalwebapp",
                ])
            except SystemExit:
                pass
            m.assert_called_once_with(
                "o/r", "123", timeout_sec=42, project="externalwebapp",
            )

    def test_trigger_with_inputs(self):
        with mock.patch.object(github_actions, "cmd_trigger") as m:
            try:
                github_actions.main([
                    "trigger", "o/r", "deploy.yml",
                    "--ref", "dev",
                    "--input", "env=staging",
                    "--input", "tag=v1",
                    "--project", "externalwebapp",
                ])
            except SystemExit:
                pass
            m.assert_called_once_with(
                "o/r", "deploy.yml",
                ref="dev",
                inputs={"env": "staging", "tag": "v1"},
                project="externalwebapp",
            )

    def test_failed_log_args(self):
        with mock.patch.object(github_actions, "cmd_failed_log") as m:
            try:
                github_actions.main([
                    "failed-log", "o/r", "555", "--tail-lines", "25",
                    "--project", "externalwebapp",
                ])
            except SystemExit:
                pass
            m.assert_called_once_with(
                "o/r", "555", tail_lines=25, project="externalwebapp",
            )

    def test_failed_log_default_tail(self):
        with mock.patch.object(github_actions, "cmd_failed_log") as m:
            try:
                github_actions.main([
                    "failed-log", "o/r", "555", "--project", "externalwebapp",
                ])
            except SystemExit:
                pass
            m.assert_called_once_with(
                "o/r", "555", tail_lines=50, project="externalwebapp",
            )

    def test_project_is_required(self):
        with pytest.raises(SystemExit) as exc_info:
            github_actions.main(["poll", "o/r", "123"])
        assert exc_info.value.code == 2

    def test_no_subcmd_exits_1(self):
        with pytest.raises(SystemExit) as exc_info:
            github_actions.main([])
        assert exc_info.value.code == 1
