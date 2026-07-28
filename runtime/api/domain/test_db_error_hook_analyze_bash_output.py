"""Unified DB-error hook output-analysis tests."""

from yoke_core.domain.db_error_hook import analyze_bash_output


# ---------------------------------------------------------------------------
# analyze_bash_output (unified)
# ---------------------------------------------------------------------------


class TestAnalyzeBashOutput:
    def test_no_issues(self):
        result = analyze_bash_output("echo hello", "hello")
        assert result is None

    def test_stray_db_detected(self, tmp_path):
        stray = tmp_path / "yoke.db"
        stray.touch()
        (tmp_path / "runtime" / "ouroboros").mkdir(parents=True)

        result = analyze_bash_output(
            "some command",
            "ok",
            repo_root=str(tmp_path),
        )
        assert result is not None
        assert "HARD STOP" in result
