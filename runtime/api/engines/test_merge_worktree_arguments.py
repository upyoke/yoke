"""Merge lock argument parsing and generated-path matching."""

from yoke_core.engines import merge_worktree
from runtime.api.engines._merge_worktree_test_helpers import mw_db as mw_db


class TestMergeLockCLI:
    def test_check_command(self, mw_db):
        from yoke_core.domain.merge_lock import main as lock_main

        result = lock_main(["check"])
        assert result == 0

    def test_acquire_release_command(self, mw_db):
        from yoke_core.domain.merge_lock import main as lock_main

        # Capture session_id from acquire
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            result = lock_main(["acquire", "YOK-9999"])
        assert result == 0
        session_id = f.getvalue().strip()
        assert session_id

        # Now release it
        result = lock_main(["release", session_id, "YOK-9999"])
        assert result == 0

    def test_force_clear_command(self, mw_db):
        from yoke_core.domain.merge_lock import main as lock_main

        result = lock_main(["force-clear"])
        assert result == 0

    def test_unknown_command(self, mw_db):
        from yoke_core.domain.merge_lock import main as lock_main

        result = lock_main(["bogus"])
        assert result == 2


class TestGlobMatching:
    def test_matches_exact(self):
        assert (
            merge_worktree._matches_glob(".yoke/BOARD.md", [".yoke/BOARD.md"]) is True
        )

    def test_matches_wildcard(self):
        assert (
            merge_worktree._matches_glob(".yoke/backups/042.md", [".yoke/backups/*"])
            is True
        )

    def test_no_match(self):
        assert merge_worktree._matches_glob("src/app.js", [".yoke/backups/*"]) is False
