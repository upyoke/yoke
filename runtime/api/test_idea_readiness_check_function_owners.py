"""Coverage for ``verify_function_owners`` (AC-1/2/3/10/16 of the
pre-handoff readiness checks).

Split off from ``test_idea_readiness_check.py`` to keep each test module
within the file-line budget; behavior and test names are preserved so
verification stays grep-able.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import (
    idea_readiness_check,
    idea_readiness_check_rg,
)
from yoke_core.domain.idea_readiness_check import verify_function_owners


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture(autouse=True)
def _reset_rg_warning_flag():
    """Reset the once-per-process rg-missing warning flag between tests."""
    idea_readiness_check_rg._warning_emitted = False
    yield
    idea_readiness_check_rg._warning_emitted = False


@pytest.fixture
def stub_repo_root(tmp_path, monkeypatch):
    """Stub _resolve_repo_root so module file lookups land in tmp_path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    monkeypatch.chdir(repo)
    return repo


@pytest.fixture
def stubbed_rg(monkeypatch, stub_repo_root):
    """Stub rg availability and ``subprocess.run`` so AC-16 owner-verification
    tests pass deterministically without depending on a real ``rg`` binary on
    PATH. The stub re-implements the matching subset of rg's behavior used by
    ``verify_function_owners`` (regex search, exit 0 on match, exit 1 on miss).
    """
    monkeypatch.setattr(
        idea_readiness_check, "rg_available",
        lambda: "/usr/bin/rg-stub",
    )
    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and list(cmd[:1]) == ["rg"]:
            pattern = cmd[2]
            target = cmd[3]
            try:
                with open(target, encoding="utf-8") as fp:
                    content = fp.read()
            except OSError:
                return subprocess.CompletedProcess(cmd, 1, "", "")
            if re.search(pattern, content, re.MULTILINE):
                return subprocess.CompletedProcess(cmd, 0, "1:match\n", "")
            return subprocess.CompletedProcess(cmd, 1, "", "")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(idea_readiness_check.subprocess, "run", _fake_run)
    return stub_repo_root


def _write_module(repo: Path, rel: str, body: str):
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)


def _write_yoke_core_domain_module(repo: Path, name: str, body: str):
    _write_module(
        repo,
        f"packages/yoke-core/src/yoke_core/domain/{name}.py",
        body,
    )


class TestVerifyFunctionOwners:
    def test_happy_path_function_resolves(self, stubbed_rg):
        _write_yoke_core_domain_module(
            stubbed_rg,
            "foo",
            "def my_function():\n    pass\n",
        )
        spec = "`yoke_core.domain.foo.my_function` extends behavior."
        issues = verify_function_owners(spec)
        assert issues == []

    def test_verb_before_reference_is_checked(self, stubbed_rg):
        _write_yoke_core_domain_module(
            stubbed_rg,
            "foo",
            "def my_function():\n    pass\n",
        )
        spec = "Extend `yoke_core.domain.foo.my_function` for intake."
        issues = verify_function_owners(spec)
        assert issues == []

    def test_runtime_api_reference_uses_runtime_source_path(self, stubbed_rg):
        _write_module(
            stubbed_rg,
            "runtime/api/domain/foo.py",
            "def my_function():\n    pass\n",
        )
        spec = "`runtime.api.domain.foo.my_function` extends behavior."
        issues = verify_function_owners(spec)
        assert issues == []

    def test_yoke_core_reference_does_not_alias_runtime_path(self, stubbed_rg):
        _write_module(
            stubbed_rg,
            "runtime/api/domain/foo.py",
            "def my_function():\n    pass\n",
        )
        spec = "`yoke_core.domain.foo.my_function` extends behavior."
        issues = verify_function_owners(spec)
        assert [i.code for i in issues] == ["UNRESOLVED_MODULE"]
        assert issues[0].context["module_path"] == (
            "packages/yoke-core/src/yoke_core/domain/foo.py"
        )

    def test_unresolved_module_only_flags_with_verb(self, stubbed_rg):
        spec = "`yoke_core.domain.ghost.helper` edits things."
        issues = verify_function_owners(spec)
        assert any(i.code == "UNRESOLVED_MODULE" for i in issues)

    def test_unresolved_function_surfaces_issue(self, stubbed_rg):
        _write_yoke_core_domain_module(
            stubbed_rg,
            "foo",
            "def something_else():\n    pass\n",
        )
        # Verb after the reference (matches the regex pattern).
        spec = "`yoke_core.domain.foo.missing_func` extends behavior."
        issues = verify_function_owners(spec)
        assert any(i.code == "UNRESOLVED_FUNCTION" for i in issues)

    def test_no_verb_no_issue(self, stubbed_rg):
        # Bare reference without a verb — not flagged.
        spec = "See `yoke_core.domain.foo.helper` for context."
        issues = verify_function_owners(spec)
        assert issues == []

    def test_missing_rg_returns_empty_without_subprocess(
        self, monkeypatch, stub_repo_root,
    ):
        """AC-1 / AC-3 / AC-10: when ``rg`` is absent, ``verify_function_owners``
        returns ``[]`` regardless of the spec text and never reaches
        ``subprocess.run``.
        """
        monkeypatch.setattr(
            idea_readiness_check, "rg_available", lambda: None,
        )

        def _explode(*args, **kwargs):
            raise AssertionError(
                "subprocess.run must not be called when rg is missing"
            )

        monkeypatch.setattr(
            idea_readiness_check.subprocess, "run", _explode,
        )
        spec = (
            "`yoke_core.domain.foo.helper` extends behavior."
            " Also `yoke_core.domain.bar.qux` modifies state."
        )
        assert verify_function_owners(spec) == []

    def test_missing_rg_warning_emitted_once(
        self, monkeypatch, caplog, stub_repo_root,
    ):
        """AC-2: missing ``rg`` emits exactly one ``WARNING`` per process."""
        monkeypatch.setattr(
            idea_readiness_check_rg.shutil, "which", lambda name: None,
        )
        with caplog.at_level(
            "WARNING", logger="yoke_core.domain.idea_readiness_check_rg",
        ):
            assert verify_function_owners(
                "Extend `yoke_core.domain.foo.helper`."
            ) == []
            assert verify_function_owners(
                "Modify `yoke_core.domain.bar.qux`."
            ) == []
        rg_warnings = [
            record for record in caplog.records
            if "rg not on PATH" in record.getMessage()
        ]
        assert len(rg_warnings) == 1
