"""Tests for yoke_core.domain.events_crud — event registry and discover."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import events_crud as ec
from runtime.api.events_crud_test_fixtures import db_path as db_path
from runtime.api.fixtures.file_test_db import connect_test_db


class TestRegistry:
    def _seed_test_event(self, db_path: str, name: str = "TestEvent") -> None:
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "INSERT INTO event_registry "
                "(event_name, event_kind, event_type, owner_service, description) "
                "VALUES (%s, 'system', 'tool_call', 'cli', 'A test event')",
                (name,),
            )
            conn.commit()
        finally:
            conn.close()

    def test_get(self, db_path: str) -> None:
        self._seed_test_event(db_path)
        result = ec.cmd_registry_get(db_path, "TestEvent")
        assert "TestEvent" in result
        assert "system" in result

    def test_list(self, db_path: str) -> None:
        """Registry list matches shell output format."""
        self._seed_test_event(db_path, "EventA")
        self._seed_test_event(db_path, "EventB")
        result = ec.cmd_registry_list(db_path)
        assert "EventA" in result
        assert "EventB" in result

    def test_list_with_kind_filter(self, db_path: str) -> None:
        self._seed_test_event(db_path, "SystemEvt")
        assert "SystemEvt" in ec.cmd_registry_list(db_path, kind="system")
        assert "SystemEvt" not in ec.cmd_registry_list(db_path, kind="lifecycle")

    def test_count(self, db_path: str) -> None:
        self._seed_test_event(db_path, "Evt1")
        self._seed_test_event(db_path, "Evt2")
        assert ec.cmd_registry_count(db_path) == 2

    def test_get_not_found(self, db_path: str) -> None:
        with pytest.raises(LookupError):
            ec.cmd_registry_get(db_path, "NonExistent")


class TestDiscover:
    def test_discover_skill_md(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / ".agents" / "skills" / "yoke" / "conduct"
        skills_dir.mkdir(parents=True)

        (skills_dir / "SKILL.md").write_text(
            "# Conduct\n"
            'yoke events emit --name "SkillEvent" --kind lifecycle\n'
        )

        result = ec.cmd_registry_discover(str(tmp_path))
        assert "SkillEvent" in result

    def test_discover_excludes_tests(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core" / "domain"
        pkg_dir.mkdir(parents=True)

        (pkg_dir / "test_emitters.py").write_text(
            'def test_emit():\n    emit_event("TestOnlyEvent", context={})\n'
        )

        result = ec.cmd_registry_discover(str(tmp_path))
        assert "TestOnlyEvent" not in result

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

    def test_discover_module_event_name_constant(self, tmp_path: Path) -> None:
        pkg_dir = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core" / "domain"
        pkg_dir.mkdir(parents=True)

        (pkg_dir / "field_notes.py").write_text(
            'FIELD_NOTE_EVENT_NAME = "OuroborosFieldNoteAppended"\n'
            "def append():\n"
            "    emit_event(event_name=FIELD_NOTE_EVENT_NAME)\n"
        )

        result = ec.cmd_registry_discover(str(tmp_path))
        expected_rel = "packages/yoke-core/src/yoke_core/domain/field_notes.py"
        assert f"OuroborosFieldNoteAppended|{expected_rel}" in result
