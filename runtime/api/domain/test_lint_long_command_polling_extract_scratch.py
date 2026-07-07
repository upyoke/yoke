"""Tests for ``lint_long_command_polling_extract_scratch``.

The sibling owns the helper-resolved-scratch-path classification used
by the polling lint's denial messages and audit emission. Tests cover
the explicit helper root, the legacy ``tempfile.gettempdir()`` /
``/tmp`` / ``/private/tmp`` shapes, and the rejection path for
non-scratch inputs.
"""

from __future__ import annotations

import unittest

from yoke_core.domain import lint_long_command_polling_extract_scratch as ext_scratch
from yoke_core.domain import project_scratch_dir


class TestScratchPathRoots(unittest.TestCase):
    def test_helper_root_appears_first(self) -> None:
        roots = ext_scratch.scratch_path_roots()
        helper_root = str(project_scratch_dir.scratch_root()).rstrip("/")
        self.assertIn(helper_root, roots)
        self.assertEqual(roots[0], helper_root)

    def test_legacy_tmp_prefixes_present(self) -> None:
        roots = ext_scratch.scratch_path_roots()
        self.assertIn("/tmp", roots)
        self.assertIn("/private/tmp", roots)

    def test_no_duplicates(self) -> None:
        roots = ext_scratch.scratch_path_roots()
        self.assertEqual(len(roots), len(set(roots)))


class TestIsHelperResolvedScratchPath(unittest.TestCase):
    def test_helper_resolved_path_recognized(self) -> None:
        helper_root = str(project_scratch_dir.scratch_root())
        capture = f"{helper_root}/watcher-captures/yoke-pytest.raw.abc.log"
        self.assertTrue(ext_scratch.is_helper_resolved_scratch_path(capture))

    def test_helper_root_itself_recognized(self) -> None:
        helper_root = str(project_scratch_dir.scratch_root()).rstrip("/")
        self.assertTrue(ext_scratch.is_helper_resolved_scratch_path(helper_root))

    def test_bare_tmp_yoke_literal_recognized(self) -> None:
        self.assertTrue(
            ext_scratch.is_helper_resolved_scratch_path("/tmp/yoke-pytest.raw.log")
        )

    def test_private_tmp_recognized(self) -> None:
        self.assertTrue(
            ext_scratch.is_helper_resolved_scratch_path(
                "/private/tmp/yoke-merge.progress.log"
            )
        )

    def test_unrelated_path_rejected(self) -> None:
        self.assertFalse(ext_scratch.is_helper_resolved_scratch_path("/etc/hosts"))
        self.assertFalse(ext_scratch.is_helper_resolved_scratch_path("./relative.log"))

    def test_empty_string_rejected(self) -> None:
        self.assertFalse(ext_scratch.is_helper_resolved_scratch_path(""))

    def test_prefix_not_a_path_component_rejected(self) -> None:
        # ``/tmpfoo`` shares characters with ``/tmp`` but is not a child of it.
        self.assertFalse(ext_scratch.is_helper_resolved_scratch_path("/tmpfoo/x.log"))


class TestOverrideEnv(unittest.TestCase):
    def test_explicit_override_root_recognized(self, *, env_key=project_scratch_dir.ENV_KEY) -> None:
        # Setting YOKE_SCRATCH_ROOT redirects scratch_root() AND
        # surfaces the override in the recognised root list, so paths
        # under the override land True even when they don't match the
        # legacy tempdir prefixes.
        import os

        prior = os.environ.get(env_key)
        try:
            os.environ[env_key] = "/tmp/yoke-scratch-test"
            roots = ext_scratch.scratch_path_roots()
            self.assertIn("/tmp/yoke-scratch-test", roots)
            self.assertTrue(
                ext_scratch.is_helper_resolved_scratch_path(
                    "/tmp/yoke-scratch-test/storage/db_error_hook/state.json"
                )
            )
        finally:
            if prior is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = prior


if __name__ == "__main__":  # pragma: no cover - direct run convenience
    unittest.main()
