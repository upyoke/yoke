"""prd_validate — heading variations, strict mode, fix guidance, DB resolution.

Split out of ``test_prd_validate.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from unittest import mock

from yoke_core.domain import prd_validate
from yoke_core.domain.prd_validate_test_helpers import (
    COMPLETE_PRD,
    _validate,
    _with_default_acs,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


class TestHeadingVariations:
    def test_test17_h3_functional_requirements_passes(self) -> None:
        """TEST 17: ### Functional Requirements under ## Requirements passes PRD-2."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Reduce errors by 50%\n\n"
            "## Requirements\n\n"
            "### Functional Requirements\n"
            "1. FR-1: Validate sections\n2. FR-2: Block on failure\n\n"
            "### Non-Functional Requirements\n1. NFR-1: Fast\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "PASS: PRD-2" in "\n".join(report.passed)
        assert report.fail_count == 0

    def test_test24_problem_statement_heading_variation(self) -> None:
        """TEST 24: 'Problem Statement' heading variation matches PRD-1."""
        body = (
            "## Problem Statement\nThis is a real problem affecting productivity and user satisfaction.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "PASS: PRD-1" in "\n".join(report.passed)
        assert report.fail_count == 0

    def test_problem_statement_synonym_why_now_passes(self) -> None:
        """`## Why now` is accepted as a Problem Statement synonym."""
        body = (
            "## Why now\nDeploys are blocking releases and the team is losing a day per week.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "PASS: PRD-1" in "\n".join(report.passed)
        assert report.fail_count == 0

    def test_problem_statement_synonym_motivation_passes(self) -> None:
        """`## Motivation` is accepted as a Problem Statement synonym."""
        body = (
            "## Motivation\nOur retention metric has fallen and the root cause is the onboarding step.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "PASS: PRD-1" in "\n".join(report.passed)
        assert report.fail_count == 0

    def test_problem_statement_synonym_background_passes(self) -> None:
        """`## Background` is accepted as a Problem Statement synonym."""
        body = (
            "## Background\nThe migration framework lacks a rehearsal path so live applies are risky.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "PASS: PRD-1" in "\n".join(report.passed)
        assert report.fail_count == 0

    def test_test25_success_criteria_matches_prd3(self) -> None:
        """TEST 25: 'Success Criteria' heading variation matches PRD-3."""
        body = (
            "## Problem Statement\nThis is a real problem affecting productivity and user satisfaction.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Criteria\n- Reduce errors by 50%"
        )
        report = _validate(_with_default_acs(body))
        assert "PASS: PRD-3" in "\n".join(report.passed)


class TestStrictModeAndGuidance:
    def test_test18_strict_mode_treats_warn_as_failure(self) -> None:
        """TEST 18: --strict mode with any WARN exits 1 (simulated via argv)."""
        body = (
            "## Problem Statement\nA real problem that needs solving for the team and users.\n\n"
            "## Goals\n- Improve by 50%\n\n"
            "## Requirements\n1. FR-1: Do something\n\n"
            "## Success Metrics\n- Reduce errors by 50%\n\n"
            "## Open Questions\n- What about edge case X?"
        )
        body_with_acs = _with_default_acs(body)
        # Confirm via domain API that the body warns.
        report = _validate(body_with_acs)
        assert report.warn_count >= 1
        assert report.fail_count == 0
        # Now simulate --strict flag via main() and verify exit 1.
        try:
            prd_validate.main(["--body-text", body_with_acs, "--strict"])
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("main() should have raised SystemExit")

    def test_test19_fix_guidance_present_on_failures(self) -> None:
        """TEST 19: Failures include 'Fix:' guidance referencing each missing section."""
        report = _validate("No sections here.")
        joined = "\n".join(report.failures)
        assert "Fix:" in joined
        assert "Requirements" in joined
        assert "Success Metrics" in joined
        assert "Goals" in joined


class TestResolveBody:
    @contextlib.contextmanager
    def _init_db(self, tmp_path: Path):
        # Backend-aware per-test DB: a SQLite file or a disposable PG
        # database with the production schema applied. resolve_body() resolves
        # its connection through db_helpers.connect(); on Postgres init_test_db
        # repoints YOKE_PG_DSN for the context's lifetime, while the tests set
        # YOKE_DB for the SQLite read path.
        with init_test_db(tmp_path) as db_path:
            yield Path(db_path)

    def _seed_item(self, db_path: Path, item_id: int, *, spec: str | None) -> None:
        # body column retired — all content goes through spec
        conn = connect_test_db(str(db_path))
        conn.execute(
            """
            INSERT INTO items (
                id, title, type, status, priority, flow, rework_count, frozen,
                spec, created_at, updated_at, source, project_id, project_sequence
            ) VALUES (%s, %s, 'issue', 'refined-idea', 'medium', 'accelerated', 0, 0, %s, %s, %s, 'user', 1, %s)
            """,
            (
                item_id,
                f"Item {item_id}",
                spec,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                item_id,
            ),
        )
        conn.commit()
        conn.close()

    def test_test20_db_backed_yok_n_reference_passes(self, tmp_path: Path) -> None:
        """TEST 20: DB-backed validation with YOK-N reference uses rendered body."""
        with self._init_db(tmp_path) as db_path:
            self._seed_item(db_path, 42, spec=COMPLETE_PRD)
            with mock.patch.dict(os.environ, {"YOKE_DB": str(db_path)}):
                body, label = prd_validate.resolve_body("YOK-42", None)
            assert label == "YOK-42"
            report = prd_validate.validate_prd(body, label)
            assert report.fail_count == 0

    def test_test21_db_item_prefers_spec_content(self, tmp_path: Path) -> None:
        """TEST 21: Spec with content is used for validation."""
        with self._init_db(tmp_path) as db_path:
            self._seed_item(db_path, 98, spec=COMPLETE_PRD)
            with mock.patch.dict(os.environ, {"YOKE_DB": str(db_path)}):
                body, label = prd_validate.resolve_body("YOK-98", None)
            report = prd_validate.validate_prd(body, label)
            assert report.fail_count == 0

    def test_test22_whitespace_only_spec_still_resolves(self, tmp_path: Path) -> None:
        """TEST 22: Whitespace-only spec still renders (via render_body)."""
        with self._init_db(tmp_path) as db_path:
            self._seed_item(db_path, 99, spec="   \n \n")
            # Whitespace spec gets rendered with a heading by build_body,
            # so resolve_body succeeds (non-empty rendered output)
            with mock.patch.dict(os.environ, {"YOKE_DB": str(db_path)}):
                body, label = prd_validate.resolve_body("YOK-99", None)
            assert label == "YOK-99"

    def test_test23_db_item_with_empty_spec_fails(self, tmp_path: Path) -> None:
        """TEST 23: Item with NULL spec exits 1 with no-body message."""
        with self._init_db(tmp_path) as db_path:
            self._seed_item(db_path, 100, spec=None)
            try:
                with mock.patch.dict(os.environ, {"YOKE_DB": str(db_path)}):
                    prd_validate.resolve_body("YOK-100", None)
            except SystemExit as exc:
                assert exc.code == 1
            else:
                raise AssertionError("resolve_body should have exited on empty body")
