"""Unit tests for the hot-path apply_patch parser surface.

Covers ``parse_patch`` / :class:`PatchPaths` consumed by
``yoke_core.domain.harness_policy_pipeline`` and other hot-path hook
consumers. The telemetry surface (``parse_patch_body`` /
:class:`ApplyPatchSummary`) lives in ``test_observe_apply_patch_parser``.

The parser must never raise — failures bottom out as empty buckets so
hook hot-paths cannot block on a bad envelope.
"""

from __future__ import annotations

import unittest

from yoke_core.domain.observe_apply_patch_parser import (
    PatchPaths,
    parse_patch,
)


class TestSingleFileCases(unittest.TestCase):
    def test_TC_add_single_file(self):
        body = (
            "*** Begin Patch\n"
            "*** Add File: docs/new.md\n"
            "+hello\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.added, ["docs/new.md"])
        self.assertEqual(result.updated, [])
        self.assertEqual(result.moved, [])
        self.assertEqual(result.deleted, [])

    def test_TC_update_single_file(self):
        body = (
            "*** Begin Patch\n"
            "*** Update File: src/foo.py\n"
            "@@\n"
            " keep\n"
            "-old\n"
            "+new\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.updated, ["src/foo.py"])
        self.assertEqual(result.added, [])
        self.assertEqual(result.deleted, [])
        self.assertEqual(result.moved, [])

    def test_TC_delete_single_file(self):
        body = (
            "*** Begin Patch\n"
            "*** Delete File: src/legacy.py\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.deleted, ["src/legacy.py"])
        self.assertEqual(result.added, [])
        self.assertEqual(result.updated, [])

    def test_TC_move_single_file(self):
        body = (
            "*** Begin Patch\n"
            "*** Update File: src/old_name.py\n"
            "*** Move to: src/new_name.py\n"
            "@@\n"
            " keep\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.updated, ["src/old_name.py"])
        self.assertEqual(result.moved, ["src/new_name.py"])


class TestMultiFileCases(unittest.TestCase):
    def test_TC_multiple_files_all_buckets(self):
        body = (
            "*** Begin Patch\n"
            "*** Add File: a/new.py\n"
            "+x\n"
            "*** Update File: b/changed.py\n"
            "@@\n"
            "-old\n"
            "+new\n"
            "*** Delete File: c/gone.py\n"
            "*** Update File: d/old.py\n"
            "*** Move to: d/renamed.py\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.added, ["a/new.py"])
        self.assertEqual(result.updated, ["b/changed.py", "d/old.py"])
        self.assertEqual(result.deleted, ["c/gone.py"])
        self.assertEqual(result.moved, ["d/renamed.py"])

    def test_TC_duplicate_paths_collapse(self):
        body = (
            "*** Begin Patch\n"
            "*** Update File: foo.py\n"
            "+a\n"
            "*** Update File: foo.py\n"
            "+b\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.updated, ["foo.py"])

    def test_TC_all_paths_helper_returns_union(self):
        body = (
            "*** Begin Patch\n"
            "*** Add File: a\n"
            "*** Update File: b\n"
            "*** Delete File: c\n"
            "*** Update File: d\n"
            "*** Move to: e\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.all_paths(), ["a", "b", "d", "e", "c"])


class TestMalformedInput(unittest.TestCase):
    """Malformed inputs return empty buckets — never raise."""

    def test_TC_empty_string(self):
        self.assertEqual(parse_patch(""), PatchPaths())

    def test_TC_none_input(self):
        self.assertEqual(parse_patch(None), PatchPaths())  # type: ignore[arg-type]

    def test_TC_non_string_input(self):
        self.assertEqual(parse_patch(12345), PatchPaths())  # type: ignore[arg-type]
        self.assertEqual(parse_patch({"foo": "bar"}), PatchPaths())  # type: ignore[arg-type]

    def test_TC_no_directives_returns_empty(self):
        body = "just some random text\nwith newlines\n"
        self.assertEqual(parse_patch(body), PatchPaths())

    def test_TC_unknown_directive_lines_skipped(self):
        body = (
            "*** Begin Patch\n"
            "*** Unknown Directive: should be ignored\n"
            "*** Add File: real/path.py\n"
            "+content\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.added, ["real/path.py"])

    def test_TC_directive_without_path_skipped(self):
        body = (
            "*** Begin Patch\n"
            "*** Add File:\n"
            "*** Update File:    \n"
            "*** Add File: real.py\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.added, ["real.py"])
        self.assertEqual(result.updated, [])

    def test_TC_no_begin_end_markers_still_parses(self):
        body = (
            "*** Add File: bare/added.py\n"
            "+x\n"
            "*** Delete File: bare/deleted.py\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.added, ["bare/added.py"])
        self.assertEqual(result.deleted, ["bare/deleted.py"])

    def test_TC_indented_directives_tolerated(self):
        body = (
            "*** Begin Patch\n"
            "    *** Add File: indented/path.py\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.added, ["indented/path.py"])

    def test_TC_paths_are_trimmed(self):
        body = (
            "*** Begin Patch\n"
            "*** Add File:    spaced/path.py   \n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.added, ["spaced/path.py"])


class TestRealisticBodies(unittest.TestCase):
    """Larger realistic envelopes to catch interaction bugs."""

    def test_TC_realistic_envelope_with_hunks(self):
        body = """*** Begin Patch
*** Update File: runtime/api/domain/example.py
@@
 from __future__ import annotations

-import os
+import os
+import sys

 def hello() -> str:
-    return "old"
+    return "new"
*** Add File: runtime/api/domain/test_example.py
+\"\"\"Tests for example.\"\"\"
+
+def test_hello():
+    pass
*** End Patch
"""
        result = parse_patch(body)
        self.assertEqual(
            result.updated, ["runtime/api/domain/example.py"]
        )
        self.assertEqual(
            result.added, ["runtime/api/domain/test_example.py"]
        )

    def test_TC_move_followed_by_unrelated_update(self):
        body = (
            "*** Begin Patch\n"
            "*** Update File: a.py\n"
            "*** Move to: b.py\n"
            "*** Update File: c.py\n"
            "@@\n"
            "+x\n"
            "*** End Patch\n"
        )
        result = parse_patch(body)
        self.assertEqual(result.updated, ["a.py", "c.py"])
        self.assertEqual(result.moved, ["b.py"])


if __name__ == "__main__":
    unittest.main()
