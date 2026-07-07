"""Tests for yoke_core.tools.render_field_note_inline."""

from __future__ import annotations

import io
import pathlib
import tempfile
import unittest
from unittest import mock

from yoke_contracts import field_note_text as rft
from yoke_core.tools import render_field_note_inline as rri


BEGIN = rri.BEGIN_MARKER
END = rri.END_MARKER


# --- Fixture helpers ---------------------------------------------------


def _wrap(body: str) -> str:
    return f"# Title\n\nIntro.\n\n{BEGIN}\n{body}{END}\n\nTrailer.\n"


def _seed_repo(root: pathlib.Path, files: dict[str, str]) -> None:
    """Write *files* under *root*, creating parent dirs as needed."""
    for rel_path, contents in files.items():
        abs_path = root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(contents, encoding="utf-8")


def _all_inventory_seeded_stale(root: pathlib.Path) -> None:
    """Seed every inventory file with stale (but well-formed) content."""
    stale = _wrap("stale-content\n")
    _seed_repo(root, {rel: stale for rel in rri.INVENTORY})


# --- Content-building tests --------------------------------------------


class TestContentBuilders(unittest.TestCase):
    def test_short_block_is_footer_plus_newline(self) -> None:
        self.assertEqual(rri._build_short_block(), rft.FOOTER + "\n")

    def test_long_block_contains_directive_and_basic_recipe(self) -> None:
        block = rri._build_long_block()
        self.assertIn(rft.DIRECTIVE, block)
        self.assertIn(rft.BASIC_RECIPE, block)
        self.assertIn(rft.HELP_POINTER, block)

    def test_long_block_contains_every_failure_mode_title(self) -> None:
        block = rri._build_long_block()
        for mode in rft.FAILURE_MODES:
            self.assertIn(mode.title, block)
            self.assertIn(mode.example_evidence, block)
            self.assertIn(mode.when_to_fire, block)

    def test_content_for_path_dispatch(self) -> None:
        self.assertEqual(
            rri._content_for_path(rri._SHARED_LONG_FORM_PATH),
            rri._build_long_block(),
        )
        self.assertEqual(
            rri._content_for_path(rri.INVENTORY[0]),
            rri._build_short_block(),
        )


# --- Marker-pair recognition (positive + negative) ---------------------


class TestRewriteBetweenMarkers(unittest.TestCase):
    def test_valid_pair_rewrites_content(self) -> None:
        original = _wrap("OLD\n")
        new = rri._rewrite_between_markers(original, "NEW\n")
        self.assertIsNotNone(new)
        self.assertIn("NEW", new)
        self.assertNotIn("OLD", new)
        self.assertIn(BEGIN, new)
        self.assertIn(END, new)

    def test_orphan_begin_returns_none(self) -> None:
        original = f"{BEGIN}\nbody-without-end\n"
        self.assertIsNone(
            rri._rewrite_between_markers(original, "REPLACEMENT\n")
        )

    def test_orphan_end_returns_none(self) -> None:
        original = f"body-without-begin\n{END}\n"
        self.assertIsNone(
            rri._rewrite_between_markers(original, "REPLACEMENT\n")
        )

    def test_end_before_begin_returns_none(self) -> None:
        original = f"{END}\nstuff\n{BEGIN}\n"
        self.assertIsNone(
            rri._rewrite_between_markers(original, "REPLACEMENT\n")
        )

    def test_two_begin_markers_unsupported(self) -> None:
        original = f"{BEGIN}\nA\n{BEGIN}\nB\n{END}\n"
        self.assertIsNone(
            rri._rewrite_between_markers(original, "REPLACEMENT\n")
        )

    def test_no_markers_at_all_returns_none(self) -> None:
        self.assertIsNone(
            rri._rewrite_between_markers("plain content\n", "REPLACEMENT\n")
        )


class TestScanForOrphans(unittest.TestCase):
    def test_clean_returns_none(self) -> None:
        self.assertIsNone(rri._scan_for_orphans(_wrap("body\n")))
        self.assertIsNone(rri._scan_for_orphans("no markers here\n"))

    def test_orphan_begin(self) -> None:
        self.assertEqual(
            rri._scan_for_orphans(f"{BEGIN}\nbody\n"),
            "BEGIN marker without matching END",
        )

    def test_orphan_end(self) -> None:
        self.assertEqual(
            rri._scan_for_orphans(f"body\n{END}\n"),
            "END marker without matching BEGIN",
        )

    def test_multiple_pairs(self) -> None:
        text = _wrap("A\n") + _wrap("B\n")
        self.assertEqual(
            rri._scan_for_orphans(text),
            "multiple marker pairs in one file (not supported)",
        )


# --- End-to-end render() against a tmp fixture --------------------------


class TestRenderEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_render_rewrites_stale_content(self) -> None:
        _all_inventory_seeded_stale(self.root)
        result = rri.render(self.root, check=False)
        self.assertEqual(len(result.changed), len(rri.INVENTORY))
        self.assertEqual(result.missing_markers, ())
        self.assertEqual(result.orphan_marker_errors, ())
        # Spot-check: short inventory file holds the FOOTER.
        sample = (self.root / rri.INVENTORY[0]).read_text(encoding="utf-8")
        self.assertIn(rft.FOOTER, sample)
        # Spot-check: long-form file holds every failure-mode title.
        long_file = (self.root / rri._SHARED_LONG_FORM_PATH).read_text(
            encoding="utf-8"
        )
        for mode in rft.FAILURE_MODES:
            self.assertIn(mode.title, long_file)

    def test_render_is_idempotent(self) -> None:
        _all_inventory_seeded_stale(self.root)
        first = rri.render(self.root, check=False)
        self.assertEqual(len(first.changed), len(rri.INVENTORY))
        second = rri.render(self.root, check=False)
        self.assertEqual(second.changed, ())
        self.assertEqual(len(second.unchanged), len(rri.INVENTORY))

    def test_check_mode_does_not_write(self) -> None:
        _all_inventory_seeded_stale(self.root)
        sample_path = self.root / rri.INVENTORY[0]
        before = sample_path.read_text(encoding="utf-8")
        result = rri.render(self.root, check=True)
        self.assertEqual(len(result.changed), len(rri.INVENTORY))
        # File on disk untouched even though render reports drift.
        self.assertEqual(sample_path.read_text(encoding="utf-8"), before)

    def test_check_mode_passes_when_no_drift(self) -> None:
        _all_inventory_seeded_stale(self.root)
        rri.render(self.root, check=False)  # write canonical content
        result = rri.render(self.root, check=True)
        self.assertEqual(result.changed, ())
        self.assertTrue(result.ok)

    def test_missing_markers_reported_but_not_fatal(self) -> None:
        # An inventory file without markers is recorded (so HCs can find
        # it) but does NOT set ok=False — marker insertion may land in a
        # later slice (Task 011).
        target = rri.INVENTORY[0]
        _seed_repo(self.root, {target: "plain content, no markers\n"})
        result = rri.render(self.root, check=False)
        names = {o.path for o in result.missing_markers}
        self.assertIn(target, names)
        self.assertTrue(result.ok)

    def test_orphan_begin_reported(self) -> None:
        target = rri.INVENTORY[0]
        _seed_repo(self.root, {target: f"{BEGIN}\nbody, no end\n"})
        result = rri.render(self.root, check=False)
        self.assertTrue(any(target in err for err in result.orphan_marker_errors))
        self.assertFalse(result.ok)

    def test_missing_file_recorded_not_fatal(self) -> None:
        # No files seeded → all inventory paths are missing.
        result = rri.render(self.root, check=False)
        self.assertEqual(len(result.missing_files), len(rri.INVENTORY))
        # Missing files do NOT set ok=False — only missing markers /
        # orphans do.
        self.assertTrue(result.ok)


# --- main() / CLI exit-code surface ------------------------------------


class TestMainCLI(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_check_mode_exits_nonzero_on_drift(self) -> None:
        _all_inventory_seeded_stale(self.root)
        buf = io.StringIO()
        with mock.patch.object(rri.sys, "stderr", buf):
            rc = rri.main(["--check", "--target-root", str(self.root)])
        self.assertEqual(rc, 1)
        self.assertIn("would change", buf.getvalue())

    def test_write_mode_exits_zero_and_writes(self) -> None:
        _all_inventory_seeded_stale(self.root)
        rc = rri.main(["--target-root", str(self.root)])
        self.assertEqual(rc, 0)
        rc_recheck = rri.main(["--check", "--target-root", str(self.root)])
        self.assertEqual(rc_recheck, 0)

    def test_orphan_markers_exit_nonzero(self) -> None:
        target = rri.INVENTORY[0]
        _seed_repo(self.root, {target: f"{BEGIN}\norphan\n"})
        buf = io.StringIO()
        with mock.patch.object(rri.sys, "stderr", buf):
            rc = rri.main(["--target-root", str(self.root)])
        self.assertEqual(rc, 1)
        err = buf.getvalue()
        self.assertIn("Orphan-marker", err)
        self.assertIn(target, err)


# --- git_pre_commit dispatch integration -------------------------------


class TestPreCommitDispatchWiring(unittest.TestCase):
    """Lock the fact that git_pre_commit.run() includes the field-note
    check as a hard-fail step after file_line_check."""

    def _patched_run(self, **rcs: int) -> tuple[int, list[str]]:
        """Run gpc.run() with each step patched to record + return rcs[name]."""
        from yoke_core.domain import git_pre_commit as gpc

        order: list[str] = []

        def record(name: str):
            def _inner():
                order.append(name)
                return rcs.get(name, 0)
            return _inner

        with (
            mock.patch.object(gpc, "_emit_diverged_warning", record("diverged")),
            mock.patch.object(gpc, "_run_file_line_check_or_block", record("file_line")),
            mock.patch.object(gpc, "_run_field_note_render_or_block", record("field_note")),
            mock.patch.object(gpc, "_run_worktree_status_check_or_block", record("worktree")),
            mock.patch.object(gpc, "_run_path_claim_coverage_check_or_block", record("path_claim")),
        ):
            rc = gpc.run()
        return rc, order

    def test_field_note_check_runs_after_file_line_check(self) -> None:
        rc, order = self._patched_run()
        self.assertEqual(rc, 0)
        self.assertEqual(
            order,
            ["diverged", "file_line", "field_note", "worktree", "path_claim"],
        )

    def test_field_note_check_hard_fails(self) -> None:
        rc, _ = self._patched_run(field_note=1)
        self.assertEqual(rc, 1)

    def test_field_note_helper_fails_closed_on_import_error(self) -> None:
        """If render_field_note_inline cannot import, helper returns 1.

        Matches the file_line_check defensive shape — silent skip on module
        breakage is worse than a hard-fail.
        """
        from yoke_core.domain import git_pre_commit as gpc

        import builtins

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if (
                name == "yoke_core.tools"
                and fromlist
                and "render_field_note_inline" in fromlist
            ):
                raise ImportError("simulated unavailable")
            return real_import(name, globals, locals, fromlist, level)

        buf = io.StringIO()
        with (
            mock.patch.object(builtins, "__import__", side_effect=fake_import),
            mock.patch.object(gpc.sys, "stderr", buf),
        ):
            rc = gpc._run_field_note_render_or_block()
        self.assertEqual(rc, 1)
        self.assertIn("field-note", buf.getvalue().lower())

    def test_field_note_helper_passes_on_clean_tree(self) -> None:
        """When render(--check) returns ok=True with no changes, rc=0."""
        from yoke_core.domain import git_pre_commit as gpc

        clean = rri.RenderResult(
            changed=(),
            unchanged=(rri.FileRenderOutcome(path="x", state="unchanged"),),
            missing_markers=(),
            missing_files=(),
            orphan_marker_errors=(),
        )
        with (
            mock.patch.object(gpc, "_resolve_repo_root", return_value="/tmp/x"),
            mock.patch.object(rri, "render", return_value=clean) as patched,
        ):
            rc = gpc._run_field_note_render_or_block()
        self.assertEqual(rc, 0)
        # Pre-commit gate MUST use check=True so it never mutates the tree.
        _, kwargs = patched.call_args
        self.assertEqual(kwargs.get("check"), True)


if __name__ == "__main__":
    unittest.main()
