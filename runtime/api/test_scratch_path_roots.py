"""Tests for ``yoke_contracts.machine_config.scratch_roots.scratch_path_roots``.

Every absolute root a Yoke scratch file may live under on this machine:
the scratch candidates first, then the OS temp roots, each ``/tmp`` or
``/var`` root paired with its macOS ``/private`` canonical twin. The hook
client reports these roots so the polling policy can recognise captures.
"""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from yoke_contracts.machine_config.runtime import SCRATCH_ROOT_ENV
from yoke_contracts.machine_config.scratch_roots import (
    scratch_path_roots,
    scratch_root_candidates,
)


class TestScratchPathRoots(unittest.TestCase):
    def test_configured_root_appears_first(self) -> None:
        roots = scratch_path_roots()
        helper_root = str(scratch_root_candidates()[0]).rstrip("/")
        self.assertEqual(roots[0], helper_root)

    def test_tmp_roots_present(self) -> None:
        roots = scratch_path_roots()
        self.assertIn("/tmp", roots)
        self.assertIn("/private/tmp", roots)

    def test_os_temp_dir_present(self) -> None:
        self.assertIn(tempfile.gettempdir().rstrip("/"), scratch_path_roots())

    def test_var_roots_get_private_twin(self) -> None:
        with mock.patch.dict("os.environ", {SCRATCH_ROOT_ENV: "/var/yoke-test"}):
            roots = scratch_path_roots()
        self.assertIn("/var/yoke-test", roots)
        self.assertIn("/private/var/yoke-test", roots)

    def test_other_roots_get_no_twin(self) -> None:
        with mock.patch.dict("os.environ", {SCRATCH_ROOT_ENV: "/opt/yoke-test"}):
            roots = scratch_path_roots()
        self.assertEqual(roots[0], "/opt/yoke-test")
        self.assertNotIn("/private/opt/yoke-test", roots)

    def test_no_duplicates(self) -> None:
        roots = scratch_path_roots()
        self.assertEqual(len(roots), len(set(roots)))

    def test_all_roots_absolute_without_trailing_slash(self) -> None:
        for root in scratch_path_roots():
            self.assertTrue(root.startswith("/"), root)
            self.assertFalse(root.endswith("/"), root)


class TestOverrideEnv(unittest.TestCase):
    def test_explicit_override_root_recognized(self) -> None:
        # Setting YOKE_SCRATCH_ROOT surfaces the override first in the
        # root list, with its /private twin.
        with mock.patch.dict(
            "os.environ", {SCRATCH_ROOT_ENV: "/tmp/yoke-scratch-test"}
        ):
            roots = scratch_path_roots()
        self.assertEqual(roots[0], "/tmp/yoke-scratch-test")
        self.assertIn("/private/tmp/yoke-scratch-test", roots)


if __name__ == "__main__":  # pragma: no cover - direct run convenience
    unittest.main()
