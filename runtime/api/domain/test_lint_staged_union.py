"""Tests for the one-call effective staged-set."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import lint_staged_union as union


def _effective(command, staged, status=None):
    with mock.patch.object(
        union, "_modified_and_untracked", return_value=status,
    ):
        return union.effective_staged_set(command, staged)


class TestPassThrough:
    def test_no_add_segments_passes_staged_through(self):
        result = _effective("git commit -m 'x'", ["a.py"])
        assert result is not None
        assert result.paths == ["a.py"]
        assert result.worktree_content_paths == frozenset()

    def test_none_staged_without_adds_stays_none(self):
        assert _effective("git commit -m 'x'", None) is None

    def test_quoted_add_text_is_not_an_add_segment(self):
        result = _effective(
            'yoke ouroboros field-note append --evidence "git add foo bombed"',
            ["a.py"],
        )
        assert result is not None
        assert result.paths == ["a.py"]
        assert result.worktree_content_paths == frozenset()


class TestDeterminateAdds:
    def test_one_call_add_targets_union_with_staged(self):
        result = _effective(
            "git add b.md c/d.py && git commit -m 'x'", ["a.py"],
        )
        assert result is not None
        assert result.paths == ["a.py", "b.md", "c/d.py"]
        assert result.worktree_content_paths == frozenset({"b.md", "c/d.py"})

    def test_add_targets_alone_when_nothing_staged(self):
        result = _effective("git add x.py && git commit -m 'x'", [])
        assert result is not None
        assert result.paths == ["x.py"]
        assert result.worktree_content_paths == frozenset({"x.py"})

    def test_add_targets_survive_failed_staged_read(self):
        # staged=None (git diff failure) must not drop the named adds.
        result = _effective("git add x.py && git commit -m 'x'", None)
        assert result is not None
        assert result.paths == ["x.py"]

    def test_path_already_staged_becomes_worktree_content(self):
        # The add overwrites the index entry, so content checks must read
        # the worktree even though the path was already staged.
        result = _effective("git add a.py && git commit -m 'x'", ["a.py"])
        assert result is not None
        assert result.paths == ["a.py"]
        assert result.worktree_content_paths == frozenset({"a.py"})

    def test_quoted_path_with_spaces(self):
        result = _effective(
            "git add 'docs/a file.md' && git commit -m 'x'", [],
        )
        assert result is not None
        assert result.paths == ["docs/a file.md"]

    def test_double_dash_separator_paths_collected(self):
        result = _effective("git add -- a.py && git commit -m 'x'", [])
        assert result is not None
        assert result.paths == ["a.py"]

    def test_add_after_commit_still_unions(self):
        # A later commit in the same body would ship it; over-inclusion
        # fails toward protection.
        result = _effective(
            "git commit -m 'one' && git add y.py && git commit -m 'two'",
            ["a.py"],
        )
        assert result is not None
        assert "y.py" in result.paths


class TestIndeterminateAdds:
    def test_add_all_widens_to_modified_and_untracked(self):
        result = _effective(
            "git add -A && git commit -m 'x'", ["a.py"],
            status=["m.py", "n.md"],
        )
        assert result is not None
        assert result.paths == ["a.py", "m.py", "n.md"]
        assert result.worktree_content_paths == frozenset({"m.py", "n.md"})

    def test_add_dot_widens(self):
        result = _effective(
            "git add . && git commit -m 'x'", [], status=["m.py"],
        )
        assert result is not None
        assert result.paths == ["m.py"]

    def test_glob_pathspec_widens(self):
        result = _effective(
            "git add docs/*.md && git commit -m 'x'", [], status=["docs/k.md"],
        )
        assert result is not None
        assert result.paths == ["docs/k.md"]

    def test_rebased_git_dash_c_widens(self):
        result = _effective(
            "git -C /elsewhere add f.py && git commit -m 'x'", [],
            status=["m.py"],
        )
        assert result is not None
        assert result.paths == ["m.py"]

    def test_commit_dash_a_self_staging_widens(self):
        result = _effective("git commit -am 'x'", ["a.py"], status=["m.py"])
        assert result is not None
        assert result.paths == ["a.py", "m.py"]
        assert result.worktree_content_paths == frozenset({"m.py"})

    def test_commit_all_long_flag_widens(self):
        result = _effective("git commit --all -m 'x'", [], status=["m.py"])
        assert result is not None
        assert result.paths == ["m.py"]

    def test_plain_dash_m_commit_does_not_widen(self):
        result = _effective("git commit -m 'all done'", ["a.py"], status=["m.py"])
        assert result is not None
        assert result.paths == ["a.py"]

    def test_status_failure_falls_back_to_visible_set(self):
        # Unavailable probe: the staged-rule family fails open — keep what
        # is still visible (staged + determinate adds).
        result = _effective(
            "git add -A b.md && git commit -m 'x'", ["a.py"], status=None,
        )
        assert result is not None
        assert result.paths == ["a.py"]

    def test_mixed_determinate_and_indeterminate_segments(self):
        result = _effective(
            "git add a.py && git add -u && git commit -m 'x'",
            [], status=["m.py"],
        )
        assert result is not None
        assert set(result.paths) == {"a.py", "m.py"}
        assert result.worktree_content_paths == frozenset({"a.py", "m.py"})


class TestStatusParsing:
    def test_porcelain_z_parse_handles_renames(self):
        raw = "M  a.py\0R  new.md\0old.md\0?? untracked.txt\0"
        completed = mock.Mock(returncode=0, stdout=raw)
        with mock.patch.object(
            union.subprocess, "run", return_value=completed,
        ):
            assert union._modified_and_untracked() == [
                "a.py", "new.md", "untracked.txt",
            ]

    def test_status_nonzero_returns_none(self):
        completed = mock.Mock(returncode=128, stdout="")
        with mock.patch.object(
            union.subprocess, "run", return_value=completed,
        ):
            assert union._modified_and_untracked() is None


class TestWorktreeBlob:
    def test_reads_file_content(self, tmp_path):
        target = tmp_path / "view.md"
        target.write_text("fresh body\n", encoding="utf-8")
        assert union.worktree_blob(str(target)) == "fresh body\n"

    def test_missing_file_returns_none(self, tmp_path):
        assert union.worktree_blob(str(tmp_path / "absent.md")) is None
