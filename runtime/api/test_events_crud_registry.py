"""Tests for yoke_core.domain.events_crud — event registry and discover."""
from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import events_crud as ec
from runtime.api.events_crud_test_fixtures import (  # noqa: F401
    db_path,
)


class TestRegistry:
    def _add_test_event(self, db_path: str, name: str = "TestEvent") -> None:
        ec.cmd_registry_add(
            db_path,
            name=name,
            kind="system",
            event_type="tool_call",
            service="cli",
            description="A test event",
        )

    def test_add_and_get(self, db_path: str) -> None:
        self._add_test_event(db_path)
        result = ec.cmd_registry_get(db_path, "TestEvent")
        assert "TestEvent" in result
        assert "system" in result

    def test_list(self, db_path: str) -> None:
        """AC-2: registry list matches shell output format."""
        self._add_test_event(db_path, "EventA")
        self._add_test_event(db_path, "EventB")
        result = ec.cmd_registry_list(db_path)
        assert "EventA" in result
        assert "EventB" in result

    def test_list_with_status_filter(self, db_path: str) -> None:
        self._add_test_event(db_path, "ActiveEvt")
        ec.cmd_registry_deprecate(db_path, "ActiveEvt")
        result = ec.cmd_registry_list(db_path, status="deprecated")
        assert "ActiveEvt" in result
        active_result = ec.cmd_registry_list(db_path, status="active")
        assert "ActiveEvt" not in active_result

    def test_update(self, db_path: str) -> None:
        self._add_test_event(db_path)
        ec.cmd_registry_update(db_path, "TestEvent", description="Updated desc")
        result = ec.cmd_registry_get(db_path, "TestEvent")
        assert "Updated desc" in result

    def test_update_not_found(self, db_path: str) -> None:
        with pytest.raises(LookupError):
            ec.cmd_registry_update(db_path, "NonExistent", description="x")

    def test_deprecate(self, db_path: str) -> None:
        self._add_test_event(db_path)
        ec.cmd_registry_deprecate(db_path, "TestEvent")
        result = ec.cmd_registry_get(db_path, "TestEvent")
        assert "deprecated" in result

    def test_deprecate_not_found(self, db_path: str) -> None:
        with pytest.raises(LookupError):
            ec.cmd_registry_deprecate(db_path, "NonExistent")

    def test_delete(self, db_path: str) -> None:
        self._add_test_event(db_path)
        ec.cmd_registry_delete(db_path, "TestEvent")
        with pytest.raises(LookupError):
            ec.cmd_registry_get(db_path, "TestEvent")

    def test_delete_not_found(self, db_path: str) -> None:
        with pytest.raises(LookupError):
            ec.cmd_registry_delete(db_path, "NonExistent")

    def test_count(self, db_path: str) -> None:
        self._add_test_event(db_path, "Evt1")
        self._add_test_event(db_path, "Evt2")
        assert ec.cmd_registry_count(db_path) == 2
        assert ec.cmd_registry_count(db_path, "active") == 2

    def test_get_not_found(self, db_path: str) -> None:
        with pytest.raises(LookupError):
            ec.cmd_registry_get(db_path, "NonExistent")

    def test_add_ignore_duplicate(self, db_path: str) -> None:
        self._add_test_event(db_path, "DupEvt")
        self._add_test_event(db_path, "DupEvt")  # should not error
        assert ec.cmd_registry_count(db_path) == 1


class TestDiscover:
    def test_discover_skill_md(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".agents" / "skills" / "yoke" / "conduct"
        skills_dir.mkdir(parents=True)

        (skills_dir / "SKILL.md").write_text(
            '# Conduct\n'
            'sh "$SCRIPT_DIR/emit-event.sh" --name "SkillEvent" --kind lifecycle\n'
        )

        result = ec.cmd_registry_discover(str(tmp_path))
        assert "SkillEvent" in result

    def test_discover_excludes_tests(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core" / "domain"
        pkg_dir.mkdir(parents=True)

        (pkg_dir / "test_emitters.py").write_text(
            "def test_emit():\n"
            '    emit_event("TestOnlyEvent", context={})\n'
        )

        result = ec.cmd_registry_discover(str(tmp_path))
        assert "TestOnlyEvent" not in result

    def test_discover_python_subprocess(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core" / "domain"
        pkg_dir.mkdir(parents=True)

        (pkg_dir / "caller.py").write_text(
            'import subprocess\n'
            'emit_script = "emit-event.sh"\n'
            'subprocess.run(["sh", emit_script, "--name", "PythonEmittedEvent"])\n'
        )

        result = ec.cmd_registry_discover(str(tmp_path))
        assert "PythonEmittedEvent" in result

    def test_discover_harness_python_parse_args_wrapper(self, tmp_path: Path) -> None:
        harness_dir = tmp_path / "runtime" / "harness"
        harness_dir.mkdir(parents=True)

        (harness_dir / "denial_telemetry.py").write_text(
            "def emit_denial_event():\n"
            "    parser = build_parser()\n"
            "    parser.parse_args([\n"
            '        "--name", "HarnessToolCallDenied",\n'
            '        "--kind", "audit",\n'
            "    ])\n"
        )

        result = ec.cmd_registry_discover(str(tmp_path))
        assert "HarnessToolCallDenied|runtime/harness/denial_telemetry.py" in result

    def test_discover_packages_python_native_emit_helpers(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core" / "engines"
        pkg_dir.mkdir(parents=True)

        (pkg_dir / "merge_worktree.py").write_text(
            "def emit_events():\n"
            '    _emit_merge_event("MergeEngineStarted", outcome="attempt")\n'
            '    _emit_event(name="MergeVerificationPassed")\n'
        )

        result = ec.cmd_registry_discover(str(tmp_path))
        expected_rel = "packages/yoke-core/src/yoke_core/engines/merge_worktree.py"
        assert f"MergeEngineStarted|{expected_rel}" in result
        assert f"MergeVerificationPassed|{expected_rel}" in result
