"""Standard user caches bypass claim checks without allowing path escapes."""

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import seed_item, seed_item_claim
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_session_cwd_path_authority
from yoke_core.domain.lint_session_cwd_validate import validate_targets

pytestmark = pytest.mark.usefixtures("bound_project_context")


@pytest.fixture
def cache_context(tmp_path, monkeypatch):
    # Remove both temp allowances so the fixture home exercises cache authority.
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setattr(
        lint_session_cwd_path_authority, "_STATIC_FREE_PATH_PREFIXES", ()
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "YOK-100").mkdir(parents=True)
    register_machine_checkout(tmp_path / "machine-config", repo, 1)
    with test_database() as conn:
        seed_item(conn, item_id=100, branch="YOK-100", repo_path=repo)
        seed_item_claim(conn, "s1", item_id=100)
        yield conn, home


@pytest.mark.parametrize("cache_root", [".cache", "Library/Caches"])
@pytest.mark.parametrize("literal_home", [False, True])
@pytest.mark.parametrize("read_only", [False, True])
def test_cache_reads_and_writes_allowed(
    cache_context, cache_root, literal_home, read_only
):
    conn, home = cache_context
    target = Path(cache_root) / "example" / "wheels" / "package.whl"
    target = f"~/{target}" if literal_home else str(home / target)
    verdict = validate_targets(
        conn,
        session_id="s1",
        targets=[target],
        read_only=read_only,
        tool_name="Read" if read_only else "Write",
    )
    assert verdict.allow


@pytest.mark.parametrize("sibling", [".cachex/f", "Library/Cachesx/f", "Documents/f"])
def test_non_cache_home_paths_still_refused(cache_context, sibling):
    conn, home = cache_context
    target = str(home / sibling)
    verdict = validate_targets(
        conn, session_id="s1", targets=[target], tool_name="Write"
    )
    assert not verdict.allow
    assert verdict.offending_target == target


@pytest.mark.parametrize("cache_root", [".cache", "Library/Caches"])
def test_cache_symlink_escape_still_refused(cache_context, cache_root):
    conn, home = cache_context
    cache = home / cache_root
    cache.mkdir(parents=True)
    private = home / "Documents"
    private.mkdir()
    (cache / "escape").symlink_to(private, target_is_directory=True)
    verdict = validate_targets(
        conn,
        session_id="s1",
        targets=[str(cache / "escape" / "f")],
        tool_name="Write",
    )
    assert not verdict.allow
    assert verdict.offending_target == str(private / "f")
