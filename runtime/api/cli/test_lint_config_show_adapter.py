"""``yoke lint config show`` must never be relayed to the server.

The report reads ``.yoke/lint-config`` from the caller's own tree. Under
the https transport a dispatcher-routed call executes server-side, where
workspace-root resolution would read the server's filesystem and report a
config the caller never edited — silently, which is the exact failure the
command exists to expose.
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import function_authz_scope
from yoke_cli.commands.adapters import lint_config


class LocalOnlyDispatchTest(unittest.TestCase):
    def _captured_kwargs(self, argv: list[str]) -> dict:
        with mock.patch.object(
            lint_config, "dispatch_and_emit", return_value=0,
        ) as dispatched:
            lint_config.lint_config_show(argv)
        self.assertTrue(dispatched.called, "adapter did not dispatch")
        return dispatched.call_args.kwargs

    def test_dispatch_is_local_only(self):
        self.assertTrue(self._captured_kwargs([]).get("local_only"))

    def test_local_only_holds_when_a_root_is_supplied(self):
        kwargs = self._captured_kwargs(["--root", "/tmp/some-checkout"])
        self.assertTrue(kwargs.get("local_only"))
        self.assertEqual(kwargs["payload"]["root"], "/tmp/some-checkout")

    def test_function_is_classified_client_local(self):
        self.assertTrue(
            function_authz_scope.is_explicit_client_local("lint.config.show"))


if __name__ == "__main__":
    unittest.main()
