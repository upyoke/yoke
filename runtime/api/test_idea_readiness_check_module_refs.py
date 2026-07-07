"""AC-6: package-submodule and planned-ref carve-outs in verify_function_owners."""

from __future__ import annotations

import unittest
from typing import Optional
from unittest.mock import patch

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

from yoke_core.domain.idea_readiness_check_refs import (
    function_refs_to_verify,
    is_module_or_planned_ref,
)
from yoke_core.domain.idea_readiness_check import verify_function_owners


_SCHEMA = """
CREATE TABLE IF NOT EXISTS path_claims (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'planned'
);
CREATE TABLE IF NOT EXISTS path_targets (
    id INTEGER PRIMARY KEY,
    path_string TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'file',
    materialization_state TEXT NOT NULL DEFAULT 'planned'
);
CREATE TABLE IF NOT EXISTS path_claim_targets (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL
);
"""


def _build_conn(
    item_id: int = 99,
    planned_paths: Optional[list] = None,
    state: str = "planned",
):
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    pg_testdb.drop_database_on_close(conn, name)
    apply_fixture_ddl(conn, _SCHEMA)
    if planned_paths:
        conn.execute(
            "INSERT INTO path_claims (id, item_id, state) VALUES (1, %s, %s)",
            (item_id, state),
        )
        for i, planned_path in enumerate(planned_paths, start=1):
            conn.execute(
                "INSERT INTO path_targets (id, path_string, kind, materialization_state) "
                "VALUES (%s, %s, 'file', 'planned')",
                (i, planned_path),
            )
            conn.execute(
                "INSERT INTO path_claim_targets (claim_id, target_id) VALUES (1, %s)",
                (i,),
            )
        conn.commit()
    return conn


class TestIsModuleOrPlannedRef(unittest.TestCase):

    def test_package_dir_returns_true(self) -> None:
        """(a) Module portion that resolves to a real package directory → True."""
        result = is_module_or_planned_ref(
            "yoke_core.tools.watch_pytest", item_id=0, conn=None
        )
        self.assertTrue(result, "runtime/api/tools/ is a package dir; should be True")

    def test_flat_module_file_ref_returns_false(self) -> None:
        """(d) Module portion is a .py file, not a dir → False (ref not carved out)."""
        result = is_module_or_planned_ref(
            "yoke_core.domain.idea_readiness_check.verify_function_owners",
            item_id=0,
            conn=None,
        )
        self.assertFalse(result, "Module .py file, not a directory → should be False")

    def test_planned_path_claim_returns_true(self) -> None:
        """(c) Full dotted path mapped to a planned path-claim target → True.

        Uses a path whose module portion is NOT a real directory, so only the
        DB check can produce True — isolating the planned-claim carve-out.
        """
        conn = _build_conn(
            item_id=99,
            planned_paths=["runtime/api/domain_nonexistent/not_yet_created.py"],
        )
        result = is_module_or_planned_ref(
            "runtime.api.domain_nonexistent.not_yet_created",
            item_id=99,
            conn=conn,
        )
        self.assertTrue(result, "Planned path-claim target → should be True")

    def test_no_dot_returns_false(self) -> None:
        """Single-segment path has no module portion; short-circuits to False."""
        result = is_module_or_planned_ref("watch_tail", item_id=0, conn=None)
        self.assertFalse(result)

    def test_planned_claim_wrong_item_not_carved_out(self) -> None:
        """(c) Planned path for a different item_id does not carve out the ref."""
        conn = _build_conn(
            item_id=99,
            planned_paths=["runtime/api/domain_nonexistent/not_yet_created.py"],
        )
        result = is_module_or_planned_ref(
            "runtime.api.domain_nonexistent.not_yet_created",
            item_id=77,  # different item — no matching claim
            conn=conn,
        )
        self.assertFalse(result, "Different item_id → planned claim must not carve out")


class TestFunctionRefsToVerify(unittest.TestCase):

    def test_edit_verb_captures_ref(self) -> None:
        """Edit verb paired with a dotted ref is extracted."""
        spec = (
            "modify `yoke_core.domain.idea_readiness_check.verify_function_owners` "
            "to add a pre-filter"
        )
        refs = function_refs_to_verify(spec)
        self.assertIn(
            (
                "yoke_core.domain.idea_readiness_check.verify_function_owners",
                "verify_function_owners",
            ),
            refs,
        )

    def test_no_verb_no_capture(self) -> None:
        """Dotted ref without an edit verb is ignored."""
        refs = function_refs_to_verify("See `yoke_core.tools.watch_pytest` for usage")
        self.assertEqual(refs, set())


class TestVerifyFunctionOwnersCarveOuts(unittest.TestCase):
    """Integration: carve-outs are applied before the rg search."""

    def test_a_package_submodule_no_issue(self) -> None:
        """(a) yoke_core.tools.watch_pytest is a package submodule → no UNRESOLVED issue."""
        spec = "modify `yoke_core.tools.watch_pytest` to add a flag"
        with patch(
            "yoke_core.domain.idea_readiness_check.rg_available",
            return_value="rg",
        ), patch(
            "yoke_core.domain.idea_readiness_check.subprocess.run",
            side_effect=AssertionError("rg must not run for package-dir refs"),
        ):
            issues = verify_function_owners(spec, conn=None, item_id=0)
        codes = [i.code for i in issues]
        self.assertNotIn("UNRESOLVED_FUNCTION", codes)
        self.assertNotIn("UNRESOLVED_MODULE", codes)

    def test_b_planned_ref_no_issue(self) -> None:
        """(b) Planned path-claim target carves out the ref before rg.

        Uses a path whose module portion is NOT a real directory so only the
        DB planned-claim check suppresses the ref.
        """
        conn = _build_conn(
            item_id=42,
            planned_paths=["runtime/api/domain_nonexistent/not_yet_created.py"],
        )
        spec = "modify `runtime.api.domain_nonexistent.not_yet_created` to stream output"
        with patch(
            "yoke_core.domain.idea_readiness_check.rg_available",
            return_value="rg",
        ), patch(
            "yoke_core.domain.idea_readiness_check.subprocess.run",
            side_effect=AssertionError("rg must not run for planned refs"),
        ):
            issues = verify_function_owners(spec, conn=conn, item_id=42)
        codes = [i.code for i in issues]
        self.assertNotIn("UNRESOLVED_FUNCTION", codes)
        self.assertNotIn("UNRESOLVED_MODULE", codes)

    def test_planned_ref_classified_when_rg_missing(self) -> None:
        """Planned refs are classified before the optional rg guard."""
        conn = _build_conn(
            item_id=42,
            planned_paths=["runtime/api/domain_nonexistent/not_yet_created.py"],
        )
        spec = "modify `runtime.api.domain_nonexistent.not_yet_created` to stream output"
        with patch(
            "yoke_core.domain.idea_readiness_check.rg_available",
            return_value=None,
        ), patch(
            "yoke_core.domain.idea_readiness_check.is_module_or_planned_ref",
            wraps=is_module_or_planned_ref,
        ) as classifier:
            issues = verify_function_owners(spec, conn=conn, item_id=42)
        self.assertEqual(issues, [])
        classifier.assert_called_once()

    def test_d_real_module_ref_passes_through(self) -> None:
        """(d) A true function ref on a .py module is NOT carved out by the pre-filter."""
        result = is_module_or_planned_ref(
            "yoke_core.domain.idea_readiness_check.nonexistent_fn",
            item_id=0,
            conn=None,
        )
        self.assertFalse(
            result,
            "Module .py file ref must not be carved out — it should reach the rg check",
        )


if __name__ == "__main__":
    unittest.main()
