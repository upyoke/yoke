"""AC-6 / AC-7 tests for :mod:`lint_workspace_repo_root_scan`.

Covers the static-scan helper that flags direct ``_repo_root`` references
(``from ... import _repo_root``, ``agents_render._repo_root(...)``,
``mock.patch("...agents_render._repo_root"...)``) outside the canonical
allowlist. The PreToolUse Bash hook in :mod:`lint_workspace_cwd_match`
audits *outer* writer-class invocations; this helper catches the inner
reader-hot-path leak shape the workspace anchor closes.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.lint_workspace_repo_root_scan import (
    REPO_ROOT_REFERENCE_ALLOWLIST,
    scan_repo_root_references,
)
from runtime.api.domain.test_agents_render_workspace_fixtures import (
    resolve_live_repo_root,
)


def _seed_source_tree(repo: Path, files: dict[str, str]) -> None:
    """Write each (rel_path, content) pair under the synthetic repo root."""
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


def test_scan_flags_renderer_module_importing_repo_root(tmp_path: Path) -> None:
    """AC-6 positive case: a renderer-adjacent module importing `_repo_root`
    is flagged when its path is not in :data:`REPO_ROOT_REFERENCE_ALLOWLIST`."""
    bad_rel = (
        "packages/yoke-core/src/yoke_core/domain/"
        "agents_render_new_consumer.py"
    )
    assert bad_rel not in REPO_ROOT_REFERENCE_ALLOWLIST, (
        "fixture path must not be allowlisted, otherwise the scan is a no-op"
    )
    _seed_source_tree(tmp_path, {
        bad_rel: (
            "from yoke_core.domain.agents_render import _repo_root\n\n"
            "def get_root():\n"
            "    return _repo_root()\n"
        ),
    })
    violations = scan_repo_root_references(tmp_path)
    assert any(bad_rel in v and "_repo_root" in v for v in violations), (
        f"expected violation for {bad_rel}, got {violations}"
    )


def test_scan_does_not_flag_allowlisted_cli_re_export(tmp_path: Path) -> None:
    """AC-6 negative case: the renderer module re-exports `_repo_root` for
    CLI/legacy consumers; that file is in the allowlist and must not flag."""
    allowlisted_rel = "packages/yoke-core/src/yoke_core/domain/agents_render.py"
    assert allowlisted_rel in REPO_ROOT_REFERENCE_ALLOWLIST
    _seed_source_tree(tmp_path, {
        allowlisted_rel: (
            "from yoke_core.domain.agents_render_workspace import _repo_root\n"
            "__all__ = ['_repo_root']\n"
        ),
    })
    violations = scan_repo_root_references(tmp_path)
    assert not any(allowlisted_rel in v for v in violations), (
        f"allowlisted CLI re-export must not flag, got {violations}"
    )


def test_scan_flags_test_fixture_that_calls_repo_root_directly(
    tmp_path: Path,
) -> None:
    """AC-7: a hypothetical `test_*.py` file that imports `_repo_root` and
    calls it inside a fixture is flagged. The lint surfaces the leak shape
    that the rewritten ``test_agents_render.repo_root`` fixture used to
    have before this ticket replaced it with the workspace-anchored helper.
    """
    bad_rel = "runtime/api/domain/test_some_renderer_consumer.py"
    assert bad_rel not in REPO_ROOT_REFERENCE_ALLOWLIST
    _seed_source_tree(tmp_path, {
        bad_rel: (
            "import pytest\n"
            "from yoke_core.domain.agents_render import _repo_root\n\n"
            "@pytest.fixture\n"
            "def repo_root():\n"
            "    return _repo_root()\n"
        ),
    })
    violations = scan_repo_root_references(tmp_path)
    assert any(bad_rel in v for v in violations), (
        f"expected fixture violation for {bad_rel}, got {violations}"
    )


def test_scan_flags_mock_patch_against_repo_root_symbol(tmp_path: Path) -> None:
    """AC-6: ``mock.patch("...agents_render._repo_root", ...)`` is the third
    leak shape and must be flagged. This is the pattern the prior
    `detect_drift` tests used before they were rewritten to pass
    `target_root=` explicitly.
    """
    bad_rel = "runtime/api/domain/test_render_drift_consumer.py"
    assert bad_rel not in REPO_ROOT_REFERENCE_ALLOWLIST
    _seed_source_tree(tmp_path, {
        bad_rel: (
            "from unittest.mock import patch\n\n"
            "def test_x():\n"
            "    with patch(\"yoke_core.domain.agents_render._repo_root\",\n"
            "               return_value=None):\n"
            "        pass\n"
        ),
    })
    violations = scan_repo_root_references(tmp_path)
    assert any(bad_rel in v and "patch" in v for v in violations), (
        f"expected mock.patch violation for {bad_rel}, got {violations}"
    )


def test_scan_returns_empty_when_no_violations(tmp_path: Path) -> None:
    """AC-6: a runtime tree without any `_repo_root` reference is clean."""
    _seed_source_tree(tmp_path, {
        "runtime/api/domain/some_module.py": "def f():\n    return 1\n",
        "runtime/harness/some_helper.py": "x = 2\n",
    })
    assert scan_repo_root_references(tmp_path) == []


def test_scan_skips_generated_package_build_output(tmp_path: Path) -> None:
    """setuptools build/lib source copies are generated output, not live source."""
    _seed_source_tree(tmp_path, {
        "packages/yoke-core/build/lib/yoke_core/domain/copied_module.py": (
            "from yoke_core.domain.agents_render import _repo_root\n"
        ),
    })
    assert scan_repo_root_references(tmp_path) == []


def test_live_tree_repo_root_scan_is_clean() -> None:
    """ratchet: the live Yoke tree carries zero violations.

    Walks the actual repo via the workspace-anchored fixture. Any new
    code path that imports or calls ``agents_render._repo_root`` outside
    the allowlist will surface here as a structural drift signal.
    """
    violations = scan_repo_root_references(resolve_live_repo_root())
    assert violations == [], (
        "live Yoke tree has unsanctioned `_repo_root` references:\n  "
        + "\n  ".join(violations)
    )
