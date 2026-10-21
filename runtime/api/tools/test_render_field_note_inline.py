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

    def test_content_for_path_is_the_short_footer(self) -> None:
        self.assertEqual(
            rri._content_for_path(rri._SHARED_LONG_FORM_PATH),
            rri._build_short_block(),
        )
        self.assertEqual(
            rri._content_for_path(rri.INVENTORY[0]),
            rri._build_short_block(),
        )


# --- Marker-pair recognition (positive + negative) ---------------------


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
        long_file = (self.root / rri._SHARED_LONG_FORM_PATH).read_text(encoding="utf-8")
        self.assertIn(rft.FOOTER, long_file)

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


if __name__ == "__main__":
    unittest.main()
