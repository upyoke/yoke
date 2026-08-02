"""Tests for HC-acceptance-criterion-provenance.

The check blocks work-item criterion labels that leak into live prose, where a
reader who only has the repository cannot resolve them. Its whole value depends
on the exemption model being right in both directions: a freshly introduced
label anywhere non-exempt must FAIL, while the surfaces that legitimately carry
the token — the checkbox format the product emits and parses, the agent bodies
that teach it, and every rendered mirror of those bodies — must stay silent.

The rendered-adapter case is the one that shipped this check red: the exemption
named two harness adapter directories by hand, a third harness was onboarded,
and its mirror of an already-exempt agent body became a failure. Those tests
assert the derived coverage rather than a fixed list, so onboarding a fourth
harness cannot reintroduce it.

This module never spells a bare criterion token in prose. The check scans its
own tree, so an illustrative example here would make it flag this file — the
same self-reference trap the module under test avoids.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yoke_core.domain.agents_render_conditional import RENDERED_AGENT_DIRS
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_acceptance_criterion_provenance as hc

_CHECK_ID = "acceptance-criterion-provenance"

#: Built by concatenation so this file carries no literal criterion token and
#: stays clean under the very check it exercises.
_LABEL = "AC" + "-3"
_CHECKBOX_LINE = f"- [ ] {_LABEL}: the request returns a receipt."


def _make_args() -> DoctorArgs:
    return DoctorArgs(
        file=None,
        fix=False,
        only=None,
        quick=False,
        project="yoke",
        db_path="unused",
    )


def _write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _run_hc(root: Path) -> RecordCollector:
    rec = RecordCollector()
    with mock.patch.object(hc, "_resolve_repo_root", return_value=str(root)):
        hc.hc_acceptance_criterion_provenance(None, _make_args(), rec)
    return rec


def _only_result(rec: RecordCollector):
    matching = [r for r in rec.results if r.check_id == _CHECK_ID]
    assert len(matching) == 1, matching
    return matching[0]


class TestFreshProvenanceFails(unittest.TestCase):
    """A new label in non-exempt prose is the whole point of the check."""

    def test_docstring_label_in_test_prose_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "runtime/api/domain/test_widget.py",
                f'"""{_LABEL}: the widget rejects a negative count."""\n',
            )
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "FAIL", result.detail)
        self.assertIn("runtime/api/domain/test_widget.py", result.detail)

    def test_comment_label_in_live_module_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "runtime/api/widget.py", f"# {_LABEL} guard: reject empties.\n")
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "FAIL", result.detail)
        self.assertIn("runtime/api/widget.py", result.detail)

    def test_markdown_prose_label_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "docs/widget-notes.md", f"Implements {_LABEL} for receipts.\n")
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "FAIL", result.detail)
        self.assertIn("docs/widget-notes.md", result.detail)

    def test_clean_tree_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "runtime/api/widget.py", "# Reject empty payloads.\n")
            _write(root, "docs/widget-notes.md", "The widget rejects empties.\n")
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "PASS", result.detail)


class TestCheckboxFormatNeverFlagged(unittest.TestCase):
    """The label format the product emits and parses is data, not provenance."""

    def test_checkbox_line_is_data_wherever_it_appears(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # A synthetic item-body fixture in an otherwise non-exempt test.
            _write(
                root,
                "runtime/api/domain/test_body_render.py",
                f'BODY = """## Acceptance Criteria\n{_CHECKBOX_LINE}\n"""\n',
            )
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "PASS", result.detail)

    def test_checked_box_variant_is_also_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "runtime/api/domain/test_body_render.py",
                f"# - [x] {_LABEL}: already satisfied.\n",
            )
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "PASS", result.detail)

    def test_prose_label_beside_a_checkbox_still_fails(self) -> None:
        # Exemption is per line, not per file: a fixture does not launder the
        # authored provenance sitting next to it.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "runtime/api/domain/test_body_render.py",
                f"{_CHECKBOX_LINE}\n# {_LABEL} motivated this fixture.\n",
            )
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "FAIL", result.detail)


class TestExemptionFamilies(unittest.TestCase):
    """Each declared family suppresses what it is meant to suppress."""

    def test_canonical_agent_bodies_are_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "runtime/agents/boss.md", f'Cite exactly, e.g. "{_LABEL} says".\n')
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "PASS", result.detail)

    def test_archive_root_is_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "docs/archive/decisions/receipts.md", f"Shipped under {_LABEL}.\n")
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "PASS", result.detail)

    def test_generated_mirror_tree_is_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/install_bundle_tree/runtime/agents/boss.md",
                f'Cite exactly, e.g. "{_LABEL} says".\n',
            )
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "PASS", result.detail)

    def test_label_format_emitter_is_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/domain/prd_validate.py",
                f'LABEL_PATTERN = r"{_LABEL}"\n',
            )
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "PASS", result.detail)

    def test_format_under_test_surface_is_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "runtime/api/domain/test_normalize_ac_labels.py",
                f'self.assertNotIn("{_LABEL}", normalized)\n',
            )
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "PASS", result.detail)


class TestRenderedAdapterCoverage(unittest.TestCase):
    """Every rendered mirror inherits the canonical body's exemption.

    Parametrized over the renderer's own directory list rather than a fixed
    set, so onboarding a harness extends this coverage automatically instead of
    turning the check red.
    """

    def test_every_rendered_adapter_dir_is_exempt(self) -> None:
        for directory in RENDERED_AGENT_DIRS:
            with self.subTest(adapter_dir=directory.as_posix()):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    _write(
                        root,
                        f"{directory.as_posix()}/yoke-boss.md",
                        f'Cite exactly, e.g. "{_LABEL} says".\n',
                    )
                    result = _only_result(_run_hc(root))

                self.assertEqual(result.result, "PASS", result.detail)

    def test_exempt_prefixes_cover_every_rendered_adapter_dir(self) -> None:
        for directory in RENDERED_AGENT_DIRS:
            with self.subTest(adapter_dir=directory.as_posix()):
                self.assertIn(f"{directory.as_posix()}/", hc._EXEMPT_PREFIXES)

    def test_derived_dirs_match_the_renderer_output_constants(self) -> None:
        # Two encodings of the same fact: the harness registry derives the
        # directory set from the harness ids, while the renderer names each
        # output directory individually for render sequencing. Bind them so a
        # harness added to one side cannot silently skip the other — that
        # divergence is precisely what shipped this check red.
        from yoke_core.domain import agents_render

        self.assertEqual(
            set(RENDERED_AGENT_DIRS),
            {
                agents_render.CLAUDE_OUT_DIR,
                agents_render.CODEX_OUT_DIR,
                agents_render.CURSOR_OUT_DIR,
            },
        )

    def test_harness_tree_outside_the_adapter_dirs_is_still_scanned(self) -> None:
        # The exemption covers rendered agent adapters, not the whole harness
        # tree — authored harness prose stays subject to the rule.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "runtime/harness/claude/rules/session.md", f"Honor {_LABEL}.\n")
            result = _only_result(_run_hc(root))

        self.assertEqual(result.result, "FAIL", result.detail)


class TestSelfSkip(unittest.TestCase):
    def test_skips_when_no_repo_root(self) -> None:
        rec = RecordCollector()
        with mock.patch.object(hc, "_resolve_repo_root", return_value=""):
            hc.hc_acceptance_criterion_provenance(None, _make_args(), rec)
        result = _only_result(rec)
        self.assertEqual(result.result, "PASS")
        self.assertIn("No repo root resolved", result.detail)


if __name__ == "__main__":
    unittest.main()
