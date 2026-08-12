"""Shared pytest fixtures for repo-wide Yoke tests."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import sys

import pytest

from yoke_core.domain import verification_tree_binding
from yoke_core.domain import verification_tree_binding_pytest_startup as _binding


REPO_ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Tree binding
# ---------------------------------------------------------------------------
#
# The floor under every pytest entry point. The watcher wrapper, the
# generic runner, and the QA case runner each judge the tree before they
# start pytest -- but a raw ``python3 -m pytest``, an IDE run button, or a
# future entry point never passes through any of them, and a run rooted in
# a checkout the session does not hold reports a green for code nobody
# changed. Here it is unavoidable: this conftest belongs to the tree being
# collected, so the check runs wherever the invocation came from.
#
# Before the heavier imports below, and before the sub-package conftests
# that start a Postgres cluster: a refused run should cost nothing.
# ``SystemExit`` rather than a raised error, because pytest renders an
# exception during conftest import as an import-failure traceback, which
# would bury the one thing the operator needs to read.
_tree_binding = _binding.pytest_startup_verdict(str(REPO_ROOT))
if _tree_binding.refusal is not None:
    print(_tree_binding.refusal, file=sys.stderr)
    raise SystemExit(_binding.TREE_BINDING_REFUSED_EXIT_STATUS)

from yoke_core.tools import build_release  # noqa: E402


PRODUCT_WHEELHOUSE_PACKAGES = build_release.PRODUCT_PACKAGE_NAMES


def pytest_addoption(parser: pytest.Parser) -> None:
    """Accept the cross-tree override the refusal above tells you to pass.

    The check reads the flag straight off ``sys.argv`` at import time,
    long before options are parsed; registering it here is what keeps
    pytest from rejecting the very argument the refusal recommends.
    """
    parser.addoption(
        verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG,
        action="store_true",
        default=False,
        help="Collect this tree even when it is outside the session's "
        "claimed worktree. For a deliberate cross-tree run.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Say the tree-binding notice where it can actually be read.

    Global capture is already installed by the time this conftest is
    imported, so a line printed up there is swallowed on every run that
    proceeds -- the refusal survives only because the process exits
    first. A cross-tree run nobody sees, or an unverified one that reads
    like a verified one, is the exact failure the guard exists to
    prevent, so the notice waits until capture can be suspended.
    """
    if _tree_binding.notice is None:
        return
    capture = config.pluginmanager.getplugin("capturemanager")
    if capture is None:
        print(_tree_binding.notice, file=sys.stderr)
        return
    with capture.global_and_fixture_disabled():
        print(_tree_binding.notice, file=sys.stderr)


@pytest.fixture(autouse=True)
def _forbid_real_browser_launches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Require every browser-opening test path to provide an explicit fake.

    The in-process guard turns a missing stub into a test failure before the
    platform browser launcher can run.  ``BROWSER`` protects child Python
    processes as well: its command accepts the URL and exits successfully, so
    :mod:`webbrowser` never falls through to the operator's default browser.
    """
    import webbrowser

    attempts: list[object] = []
    child_attempt = tmp_path / "unexpected-browser-launch"

    def _fail(*args, **_kwargs):
        attempts.append(args[0] if args else None)
        pytest.fail(
            "Automated tests may not launch a real browser; inject a browser "
            "opener and assert the requested URL instead."
        )

    monkeypatch.setattr(webbrowser, "open", _fail)
    monkeypatch.setattr(webbrowser, "open_new", _fail)
    monkeypatch.setattr(webbrowser, "open_new_tab", _fail)
    monkeypatch.setenv(
        "BROWSER",
        shlex.join(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                str(child_attempt),
                "%s",
            ]
        ),
    )
    yield
    if attempts or child_attempt.exists():
        pytest.fail(
            "An automated test attempted to launch a browser without an "
            "explicit fake opener."
        )


@pytest.fixture(autouse=True)
def _isolate_commit_cache(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the on-disk commit/activity caches to a per-test tmp dir.

    Both caches resolve their file location through
    ``machine_config.cache_dir()`` (``~/.yoke/cache`` by default). Tests
    that rebuild the board against real temp repos otherwise write their
    throwaway-repo entries into the developer's real cache and, under xdist,
    race each other's writes there — pollution that evicted real-repo entries
    from the production cache. This monkeypatch pins the path for IN-PROCESS
    ``get_commit_data`` calls, and lives at the repo root so it covers the whole
    canonical suite (``runtime/api`` ∪ ``runtime/harness`` ∪ ``tests``).

    It CANNOT reach a spawned interpreter — a monkeypatch does not cross the
    process boundary. Subprocess board rebuilds stay off the real cache by two
    other routes, both relying on ``cache_dir()`` anchoring under
    ``yoke_home()``: the merge-worktree engine subprocess inherits the isolated
    ``YOKE_MACHINE_HOME`` its parent test sets; the core-less rebuild smoke,
    which sets no machine home, pins an explicit ``cache_dir`` in its child's
    machine config (see ``test_board_rebuild_core_less_smoke``).
    """
    from yoke_contracts.board import widgets_commit_cache as _commit_cache
    from yoke_contracts.board import activity_cache as _activity_cache

    monkeypatch.setattr(
        _commit_cache, "_cache_path",
        lambda: tmp_path / "cache" / ".commit-cache.json",
    )
    monkeypatch.setattr(
        _activity_cache, "_cache_path",
        lambda: tmp_path / "cache" / "board-activity-day-counts.json",
    )
    _commit_cache._reset_memo_for_tests()
    yield
    _commit_cache._reset_memo_for_tests()


@pytest.fixture(scope="session")
def product_wheelhouse(tmp_path_factory, pytestconfig: pytest.Config) -> Path:
    """Build the client product wheels once per pytest run."""
    worker_id = _worker_id(pytestconfig)
    if worker_id == "master":
        wheelhouse = tmp_path_factory.mktemp("product_wheelhouse")
        _build_wheelhouse(REPO_ROOT, wheelhouse)
        _write_product_wheelhouse_sentinel(wheelhouse)
        return wheelhouse

    shared_root = tmp_path_factory.getbasetemp().parent
    wheelhouse = shared_root / "product_wheelhouse"
    sentinel = wheelhouse / ".built.json"
    from filelock import FileLock

    with FileLock(str(shared_root / "product_wheelhouse.lock")):
        if not sentinel.exists():
            _build_wheelhouse(REPO_ROOT, wheelhouse)
            _write_product_wheelhouse_sentinel(wheelhouse)
    return wheelhouse


def _worker_id(pytestconfig: pytest.Config) -> str:
    worker_input = getattr(pytestconfig, "workerinput", None)
    if isinstance(worker_input, dict):
        return str(worker_input.get("workerid") or "master")
    return "master"


def _build_wheelhouse(repo_root: Path, wheelhouse: Path) -> None:
    build_release.build_product_wheelhouse(
        repo_root=repo_root,
        wheelhouse=wheelhouse,
    )


def _write_product_wheelhouse_sentinel(wheelhouse: Path) -> None:
    payload = {
        "packages": list(PRODUCT_WHEELHOUSE_PACKAGES),
        "wheels": sorted(path.name for path in wheelhouse.glob("*.whl")),
    }
    (wheelhouse / ".built.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
