"""Tests for ``yoke_core.tools.watch_inventory``."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.tools import watch_inventory


def _make_repo(tmp_path: Path) -> Path:
    """Create a fake repo root with the minimum SCAN_ROOTS structure."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# placeholder\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "runtime" / "agents").mkdir(parents=True)
    (repo / "runtime" / "harness" / "claude" / "rules").mkdir(parents=True)
    (repo / ".agents" / "skills").mkdir(parents=True)
    return repo


class TestFindResidueClean:
    def test_clean_repo_yields_no_findings(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        findings = watch_inventory.find_residue(repo)
        assert findings == []

    def test_hidden_child_dirs_are_skipped(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        hidden = repo / "docs" / ".cache"
        hidden.mkdir()
        (hidden / "stale.md").write_text(
            "tail -f /tmp/x | grep --line-buffered 'pytest'\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert findings == []


class TestFindResidueLabelledFallback:
    def test_fallback_label_within_radius_suppresses_finding(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        (repo / "docs" / "guide.md").write_text(
            "## Long commands\n"
            "Use the wrapper. Fallback documentation only:\n"
            "tail -f /tmp/x | grep --line-buffered 'foo'\n"
            "If no wrapper exists, this is the fallback path.\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert findings == []

    def test_watch_pytest_mention_within_radius_suppresses_finding(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        (repo / "runtime" / "agents" / "engineer.md").write_text(
            "Prefer watch_pytest. For commands without a wrapper:\n"
            "tail -f /tmp/x | grep --line-buffered 'foo'\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert findings == []


class TestFindResidueUnlabelled:
    def test_unlabelled_pattern_is_flagged(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "runtime" / "agents" / "engineer.md").write_text(
            "## Always do this\n"
            "tail -f /tmp/yoke-test | grep --line-buffered 'pytest'\n"
            "Run it before every merge.\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.line_number == 2
        assert "tail -f /tmp/yoke-test" in finding.line


class TestStaleMonitorProse:
    """Class-2 residue: prose teaching ``permissive `tail -f``` as Monitor."""

    def test_permissive_tail_dash_f_is_flagged(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "runtime" / "agents" / "engineer.md").write_text(
            "## Streaming\n"
            "Monitor tails the progress capture with a permissive `tail -f`.\n"
            "Run wrappers like watch_pytest for filtering.\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert len(findings) == 1
        assert findings[0].line_number == 2
        assert "permissive" in findings[0].line

    def test_permissive_phrasing_without_backticks_is_flagged(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        (repo / "AGENTS.md").write_text(
            "Point Monitor at the capture with a permissive tail -f.\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert len(findings) == 1

    def test_watch_tail_prose_is_not_flagged(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "runtime" / "agents" / "tester.md").write_text(
            "Monitor follows the progress capture via "
            "python3 -m yoke_core.tools.watch_tail <progress-capture>.\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert findings == []

    def test_fallback_context_does_not_suppress_class_2(
        self, tmp_path: Path
    ) -> None:
        # Class-2 has no fallback-context bypass: the phrase only appears
        # when teaching Monitor wrong. Even if "fallback" or "watch_pytest"
        # appears nearby, the prose still needs to be fixed.
        repo = _make_repo(tmp_path)
        (repo / "AGENTS.md").write_text(
            "Use the watch_pytest wrapper. Fallback details below.\n"
            "Monitor tails the progress capture with a permissive `tail -f`.\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert len(findings) == 1


class TestExcludesWrapperImplementation:
    def test_wrapper_files_are_not_scanned(self, tmp_path: Path) -> None:
        # Even though SCAN_ROOTS does not include runtime/api/tools, we
        # still want to confirm the explicit exclude list works when a
        # consumer extends scan roots in the future. Simulate this by
        # placing the wrapper at one of the SCAN_ROOTS entries with the
        # same trailing path — matching by ``EXCLUDE_PATHS`` resolves
        # via the repo-root prefix.
        repo = _make_repo(tmp_path)
        wrapper_dir = repo / "runtime" / "api" / "tools"
        wrapper_dir.mkdir(parents=True)
        # Forge the file at the canonical exclude path so the resolver
        # matches it.
        (wrapper_dir / "watch_pytest.py").write_text(
            "EXAMPLE = 'tail -f /tmp/x | grep --line-buffered \"pytest\"'\n",
            encoding="utf-8",
        )
        # Add another non-excluded markdown file with a labelled fallback
        # so the test exercises the full scan path.
        (repo / "AGENTS.md").write_text(
            "# Yoke\nFallback documentation:\n"
            "tail -f /tmp/x | grep --line-buffered 'foo'\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert findings == []


class TestExcludePathsRegistry:
    """The new wrappers + watch_doctor backfill must appear in
    ``EXCLUDE_PATHS`` and their tokens in ``FALLBACK_TOKENS`` so the
    residue scanner never flags the wrappers' own example text and
    never flags labelled fallback prose mentioning them.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "packages/yoke-core/src/yoke_core/tools/watch_doctor.py",
            "packages/yoke-core/src/yoke_core/tools/watch_advance.py",
            "packages/yoke-core/src/yoke_core/tools/watch_lifecycle.py",
            "packages/yoke-core/src/yoke_core/tools/watch_session_offer.py",
            "runtime/api/tools/test_watch_doctor.py",
            "runtime/api/tools/test_watch_advance.py",
            "runtime/api/tools/test_watch_lifecycle.py",
            "runtime/api/tools/test_watch_session_offer.py",
        ],
    )
    def test_wrapper_in_exclude_paths(self, path: str) -> None:
        assert path in watch_inventory.EXCLUDE_PATHS

    @pytest.mark.parametrize(
        "token",
        [
            "watch_doctor",
            "watch_advance",
            "watch_lifecycle",
            "watch_session_offer",
        ],
    )
    def test_wrapper_token_in_fallback_tokens(self, token: str) -> None:
        assert token in watch_inventory.FALLBACK_TOKENS


class TestFallbackContextSuppressionForNewWrappers:
    """Each new wrapper's name in nearby prose must suppress an
    otherwise-residue hit, mirroring the existing watch_pytest behavior.
    """

    @pytest.mark.parametrize(
        "wrapper_name",
        [
            "watch_doctor",
            "watch_advance",
            "watch_lifecycle",
            "watch_session_offer",
        ],
    )
    def test_new_wrapper_mention_suppresses_finding(
        self, tmp_path: Path, wrapper_name: str
    ) -> None:
        repo = _make_repo(tmp_path)
        (repo / "runtime" / "agents" / "engineer.md").write_text(
            f"Prefer {wrapper_name}. For commands without a wrapper:\n"
            "tail -f /tmp/x | grep --line-buffered 'foo'\n",
            encoding="utf-8",
        )
        findings = watch_inventory.find_residue(repo)
        assert findings == []


class TestCLIExitCodes:
    def test_check_returns_one_on_findings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(tmp_path)
        (repo / "AGENTS.md").write_text(
            "tail -f /tmp/x | grep --line-buffered 'pytest'\n",
            encoding="utf-8",
        )
        rc = watch_inventory.main(["check", "--repo-root", str(repo)])
        assert rc == 1
        captured = capsys.readouterr().out
        assert "unlabelled hand-authored" in captured
        assert "AGENTS.md" in captured

    def test_list_returns_zero_even_with_findings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(tmp_path)
        (repo / "AGENTS.md").write_text(
            "tail -f /tmp/x | grep --line-buffered 'pytest'\n",
            encoding="utf-8",
        )
        rc = watch_inventory.main(["list", "--repo-root", str(repo)])
        assert rc == 0

    def test_check_returns_zero_on_clean_repo(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _make_repo(tmp_path)
        rc = watch_inventory.main(["check", "--repo-root", str(repo)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no unlabelled" in out
