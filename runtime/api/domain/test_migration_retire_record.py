"""Tests for migration_retire_record (governed DB-mutation contract §8.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.db_mutation_gate_evidence import (
    _verify_retire_record,
    decision_record_path,
)
from yoke_core.domain.migration_retire_record import (
    RetireRecordError,
    write_retire_record,
)


class TestWriteRetireRecord:
    def test_creates_file_with_correct_frontmatter(self, tmp_path: Path) -> None:
        result = write_retire_record(
            project="ignored",
            module="dead_module",
            model="primary",
            reason="never applied; superseded by inline backfill",
            repo_path=tmp_path,
        )
        assert result["wrote"] is True
        assert result["unchanged"] is False
        path = decision_record_path(tmp_path, "dead_module")
        assert path.is_file()
        # The same gate that enforces the contract must accept this record.
        ok, reason = _verify_retire_record(tmp_path, "dead_module", "primary")
        assert ok, reason

    def test_idempotent_no_op_on_matching_frontmatter(self, tmp_path: Path) -> None:
        write_retire_record(
            project="ignored",
            module="m",
            model="primary",
            reason="r",
            repo_path=tmp_path,
        )
        # Tweak body in place — re-running must not clobber it.
        path = decision_record_path(tmp_path, "m")
        original = path.read_text(encoding="utf-8")
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\nOperator added context here.\n")
        edited = path.read_text(encoding="utf-8")
        result = write_retire_record(
            project="ignored",
            module="m",
            model="primary",
            reason="r",
            repo_path=tmp_path,
        )
        assert result["wrote"] is False
        assert result["unchanged"] is True
        # Body preserved.
        assert path.read_text(encoding="utf-8") == edited
        assert path.read_text(encoding="utf-8") != original

    def test_overwrite_flag_rewrites_existing(self, tmp_path: Path) -> None:
        write_retire_record(
            project="ignored",
            module="m",
            model="primary",
            reason="first",
            repo_path=tmp_path,
        )
        path = decision_record_path(tmp_path, "m")
        first = path.read_text(encoding="utf-8")
        result = write_retire_record(
            project="ignored",
            module="m",
            model="primary",
            reason="second",
            repo_path=tmp_path,
            overwrite=True,
        )
        assert result["wrote"] is True
        rewritten = path.read_text(encoding="utf-8")
        assert "second" in rewritten
        assert rewritten != first

    def test_rejects_module_with_path_separator(self, tmp_path: Path) -> None:
        with pytest.raises(RetireRecordError):
            write_retire_record(
                project="ignored",
                module="bad/path",
                model="primary",
                reason="r",
                repo_path=tmp_path,
            )

    def test_rejects_module_with_extension(self, tmp_path: Path) -> None:
        with pytest.raises(RetireRecordError):
            write_retire_record(
                project="ignored",
                module="m.py",
                model="primary",
                reason="r",
                repo_path=tmp_path,
            )

    def test_rejects_empty_reason(self, tmp_path: Path) -> None:
        with pytest.raises(RetireRecordError):
            write_retire_record(
                project="ignored",
                module="m",
                model="primary",
                reason="   ",
                repo_path=tmp_path,
            )

    def test_custom_body_used_verbatim(self, tmp_path: Path) -> None:
        body = "Operator-supplied body explaining the decision."
        write_retire_record(
            project="ignored",
            module="m",
            model="primary",
            reason="r",
            body=body,
            repo_path=tmp_path,
        )
        text = decision_record_path(tmp_path, "m").read_text(encoding="utf-8")
        assert body in text

    def test_overwrite_when_existing_record_has_different_model(
        self, tmp_path: Path
    ) -> None:
        # When the existing record names a different model, the helper must
        # rewrite (the frontmatter would otherwise mislead the gate).
        write_retire_record(
            project="ignored", module="m", model="other",
            reason="r", repo_path=tmp_path,
        )
        result = write_retire_record(
            project="ignored", module="m", model="primary",
            reason="r", repo_path=tmp_path,
        )
        assert result["wrote"] is True
        ok, _ = _verify_retire_record(tmp_path, "m", "primary")
        assert ok
