"""Command-dispatch coverage for the deployment step runners."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from yoke_core.tools import step_runners


class MainCLITests(unittest.TestCase):
    def test_auto_dispatch(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = step_runners.main(["auto"])
        self.assertEqual(rc, 0)
        self.assertIn("exec-auto", buf.getvalue())

    def test_health_check_dispatch(self) -> None:
        with mock.patch.object(step_runners, "exec_health_check", return_value=0) as m:
            rc = step_runners.main(["health-check", "http://x/"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with("http://x/", request_id="")

    def test_health_check_dispatch_with_request_id(self) -> None:
        with mock.patch.object(step_runners, "exec_health_check", return_value=0) as m:
            rc = step_runners.main(["health-check", "http://x/", "rid-9"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with("http://x/", request_id="rid-9")

    def test_ephemeral_verify_dispatch(self) -> None:
        with mock.patch.object(
            step_runners, "exec_ephemeral_verify", return_value=0
        ) as runner:
            rc = step_runners.main(
                [
                    "ephemeral-verify",
                    "externalwebapp",
                    "org/repo",
                    "br",
                    "wf.yml",
                    "d.example",
                    "abc",
                ]
            )
        self.assertEqual(rc, 0)
        runner.assert_called_once_with(
            "org/repo",
            "br",
            "wf.yml",
            "d.example",
            "abc",
            project="externalwebapp",
        )

    def test_unknown_command(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = step_runners.main(["nonsense"])
        self.assertEqual(rc, 1)
        self.assertIn("unknown step_runner", buf.getvalue())

    def test_empty_argv(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = step_runners.main([])
        self.assertEqual(rc, 1)
        self.assertIn("Usage", buf.getvalue())
