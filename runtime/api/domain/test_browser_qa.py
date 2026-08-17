"""Python backstop for the Browser method runner substrate.

The original Python port of the shell suite lived in this file alongside every
scenario class. It now hosts only requirement/base_url plumbing and
reachability/daemon-init checks so each authored
file stays under the 350-line limit. The remaining scenarios live in sibling
``test_browser_qa_*.py`` files; shared helpers live in
``browser_qa_test_helpers``.

Live browser substrate / Playwright daemon is never started in these tests —
``browser_client`` functions are patched out. Any behavior that genuinely
requires a live browser is out of scope for a pytest backstop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain import browser_qa_requirement
from yoke_core.domain import browser_qa_results
from runtime.api.domain.browser_qa_test_helpers import (
    _browser_verdict_assertion,
    _patch_external_deps,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


# ---------------------------------------------------------------------------
# No requirements / base_url handling
# ---------------------------------------------------------------------------

class TestRequirementsAndBaseUrl:
    def test_no_browser_requirements_returns_note(self, db_path: str) -> None:
        """Shell 'No requirements' case: no browser kinds → note=no_browser_requirements."""
        _seed_item(db_path, 200)

        patches = _patch_external_deps(db_path)
        for p in patches:
            p.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=200,
                project="testproj",
                requirement_id=-1,
                base_url="http://localhost:9999",
            )
        finally:
            for p in patches:
                p.stop()

        assert result.note == "no_browser_requirements"

    def test_no_base_url_no_fallback_returns_error(self, db_path: str) -> None:
        """If --base-url is empty AND success_policy has no base_url, note=no_base_url."""
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path, 100, "browser-check",
            {
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )

        result = _run_scenario(db_path, 100, base_url="")
        assert result.verdict == "error"
        assert result.note == "no_base_url"

    def test_base_url_fallback_from_success_policy(self, db_path: str) -> None:
        """Fall back to success_policy.base_url when the flag is omitted."""
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path, 100, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )

        result = _run_scenario(
            db_path, 100, base_url="",
            execute_step_responses=[{"success": True, "artifacts": []}],
        )
        assert result.verdict == "pass"
        assert result.executed >= 1


class TestReachabilityAndDaemon:
    def test_ac4_unreachable_url_exits_with_note(self, db_path: str) -> None:
        """Unreachable base_url returns verdict=error, note=unreachable."""
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path, 100, "browser-check",
            {
                "base_url": "http://unreachable.invalid",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )

        result = _run_scenario(db_path, 100, reachable=False)
        assert result.verdict == "error"
        assert result.note == "unreachable"

    def test_daemon_failure_returns_error(self, db_path: str) -> None:
        """Daemon start failure → verdict=error, note=daemon_failure."""
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path, 100, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )

        result = _run_scenario(db_path, 100, daemon_ok=False)
        assert result.verdict == "error"
        assert result.note == "daemon_failure"


class TestBrowserQaArtifactAudit:
    """Lock in the Yoke-side audit findings for qa-artifacts.

    The audit established:

    * Yoke browser QA writes artifacts under project scratch storage via
      :mod:`yoke_core.domain.browser_qa_requirement`.
    * No Yoke browser QA module force-adds artifacts via ``git add``.

    A regression that reintroduces a ``git add`` call in browser_qa modules
    or that moves artifact creation back under the repo projects tree
    surfaces here, before re-committing artifacts to a downstream repo.
    """

    BROWSER_QA_MODULES = (
        "browser_qa.py",
        "browser_qa_requirement.py",
        "browser_qa_results.py",
    )

    def test_no_git_add_calls_in_browser_qa_modules(self) -> None:
        # Repo-rooted scan: the canonical browser QA modules must not
        # invoke `git add` (or `git add -f`). Allow the literal in test
        # files where it sets up fixtures.
        modules = (browser_qa, browser_qa_requirement, browser_qa_results)
        for module in modules:
            path = Path(module.__file__)
            text = path.read_text()
            assert "git add" not in text, (
                f"{path.name} contains a 'git add' literal; "
                "browser_qa runners must never force-add artifacts."
            )

    def test_artifact_path_uses_scratch_qa_artifact_helper(self) -> None:
        source = Path(browser_qa_requirement.__file__).read_text()
        assert "artifact_directory(" in source
        assert '"projects"' not in source, (
            "browser_qa_requirement.py writes artifacts under "
            "projects/<project>/qa-artifacts/ instead of scratch storage."
        )
