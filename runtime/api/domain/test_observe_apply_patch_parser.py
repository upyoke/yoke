"""Coverage for the apply_patch body parser (telemetry API).

Tests the ``parse_patch_body`` / :class:`ApplyPatchSummary` surface used
by Codex hook payload normalization to surface changed paths into the
events ledger. The hot-path hook surface (``parse_patch`` /
:class:`PatchPaths`) lives in ``test_observe_apply_patch_parser_paths``.
"""

from __future__ import annotations

from yoke_core.domain.observe_apply_patch_parser import (
    ApplyPatchSummary,
    parse_patch_body,
)


def _wrap(inner: str) -> str:
    return "*** Begin Patch\n" + inner + "*** End Patch\n"


class TestParsePatchBody:
    def test_empty_body_returns_blank_summary(self):
        summary = parse_patch_body("")
        assert summary.changed_paths == []
        assert summary.well_formed is False

    def test_non_string_returns_blank(self):
        summary = parse_patch_body(None)  # type: ignore[arg-type]
        assert summary.changed_paths == []
        assert summary.well_formed is False

    def test_single_add(self):
        body = _wrap("*** Add File: path/a.py\n+hello\n")
        summary = parse_patch_body(body)
        assert summary.added == ["path/a.py"]
        assert summary.well_formed is True
        assert summary.changed_paths == ["path/a.py"]

    def test_single_update(self):
        body = _wrap(
            "*** Update File: src/foo.py\n@@\n-old\n+new\n"
        )
        summary = parse_patch_body(body)
        assert summary.updated == ["src/foo.py"]
        assert summary.changed_paths == ["src/foo.py"]

    def test_single_delete(self):
        body = _wrap("*** Delete File: docs/old.md\n")
        summary = parse_patch_body(body)
        assert summary.deleted == ["docs/old.md"]
        assert summary.changed_paths == ["docs/old.md"]

    def test_inline_move(self):
        body = _wrap("*** Move File: src/a.py -> src/b.py\n")
        summary = parse_patch_body(body)
        assert summary.moved == [("src/a.py", "src/b.py")]
        assert summary.changed_paths == ["src/a.py", "src/b.py"]

    def test_update_followed_by_move_to(self):
        body = _wrap(
            "*** Update File: src/a.py\n"
            "*** Move to: src/b.py\n"
            "@@\n-old\n+new\n"
        )
        summary = parse_patch_body(body)
        # The Update was promoted into a move pair, so it's no longer in
        # ``updated``.
        assert summary.updated == []
        assert summary.moved == [("src/a.py", "src/b.py")]
        assert summary.changed_paths == ["src/a.py", "src/b.py"]

    def test_multi_file_patch(self):
        body = _wrap(
            "*** Add File: new/one.py\n"
            "+content\n"
            "*** Update File: existing/two.py\n"
            "@@\n-x\n+y\n"
            "*** Delete File: old/three.py\n"
            "*** Move File: legacy/four.py -> renamed/four.py\n"
        )
        summary = parse_patch_body(body)
        assert summary.added == ["new/one.py"]
        assert summary.updated == ["existing/two.py"]
        assert summary.deleted == ["old/three.py"]
        assert summary.moved == [("legacy/four.py", "renamed/four.py")]
        assert summary.changed_paths == [
            "new/one.py",
            "existing/two.py",
            "old/three.py",
            "legacy/four.py",
            "renamed/four.py",
        ]

    def test_missing_envelope_still_extracts_paths(self):
        """A malformed payload with no Begin/End markers degrades to a
        best-effort summary rather than a silent empty result."""
        body = "*** Add File: lone.py\n+hi\n"
        summary = parse_patch_body(body)
        assert summary.added == ["lone.py"]
        assert summary.well_formed is False
        assert summary.changed_paths == ["lone.py"]

    def test_changed_paths_dedupe(self):
        body = _wrap(
            "*** Add File: dup.py\n+a\n"
            "*** Update File: dup.py\n@@\n-a\n+b\n"
        )
        summary = parse_patch_body(body)
        # Both lists carry the same path, but ``changed_paths`` collapses.
        assert summary.added == ["dup.py"]
        assert summary.updated == ["dup.py"]
        assert summary.changed_paths == ["dup.py"]

    def test_unrecognized_directives_ignored(self):
        body = _wrap(
            "*** Mystery Directive: ???\n"
            "*** Add File: ok.py\n+x\n"
        )
        summary = parse_patch_body(body)
        assert summary.added == ["ok.py"]
        assert summary.well_formed is True

    def test_summary_dataclass_default_well_formed_false(self):
        # Sanity: bare construction should reflect the documented default.
        summary = ApplyPatchSummary()
        assert summary.well_formed is False
        assert summary.changed_paths == []
