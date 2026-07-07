"""render_body — unified ``## DB Claim`` body-section rendering.

Split out of ``test_render_body.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain import render_body
from yoke_core.domain.render_body_test_helpers import (
    _connect,
    db_path,  # noqa: F401  (pytest fixture)
    _seed_item,
    _set_field,
)


class TestUnifiedDbClaimRendering:
    """Render coverage for the unified ``## DB Claim`` body section.

    Internal storage stays split across ``db_mutation_profile`` and
    ``db_compatibility_attestation``; rendered bodies show one DB-claim
    section. Negative claims (``state="none"``) and malformed JSON
    render nothing — including the residue case where ``state="none"``
    carries a stale ``frozen_at`` stamp.
    """

    def _declared_profile_json(self) -> str:
        return json.dumps({
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["add_items_due_date"],
            "compatibility_class": "pre_merge_safe",
            "migration_strategy": "additive_only",
            "schema_kinds": ["additive"],
            "data_kinds": [],
            "affected_surfaces": [
                {"table": "items", "columns": ["due_date"]}
            ],
            "count_preserving": True,
        }, sort_keys=True)

    def _authored_attestation_json(self) -> str:
        return json.dumps({
            "frozen_at": "2026-04-22T17:52:49Z",
            "pre_merge_readers_writers": [
                {"path": "runtime/api/domain/projects.py", "symbol": "load", "role": "reader"}
            ],
            "invariants": ["items.status values are drawn from canonical lifecycle"],
            "rehearsal_commands": ["python3 -m pytest runtime/api/domain/test_projects.py"],
            "residual_risk_notes": "Dashboard view one-cycle lag.",
            "rehearsal_outcomes": [
                {
                    "command": "python3 -m pytest ...",
                    "verdict": "pass",
                    "observed_at": "2026-04-22T18:00:00Z",
                },
                {
                    "command": "python3 -m pytest runtime/api/domain/test_projects.py",
                    "returncode": 0,
                    "ran_at": "2026-04-22T18:05:00Z",
                },
            ],
            "class_escalations": [
                {"from": "pre_merge_safe", "to": "pre_merge_breaking",
                 "source": "scanner", "reason": "DROP TABLE detected"}
            ],
        }, sort_keys=True)

    def test_state_none_renders_nothing(self, tmp_path: Path, db_path: str) -> None:
        conn = _connect(db_path)
        _seed_item(conn, 51, "Claim none")
        _set_field(conn, 51, "spec", "# Claim none\nContext body.")
        _set_field(conn, 51, "db_mutation_profile", '{"state":"none"}')
        body = render_body.build_body(conn, 51) or ""
        conn.close()
        assert "## DB Claim" not in body
        # The historical headings must not appear either — there is one
        # operator-facing concept now.
        assert "DB Mutation Profile" not in body
        assert "DB Compatibility Attestation" not in body

    def test_state_none_with_residue_frozen_at_renders_nothing(
        self, tmp_path: Path, db_path: str,
    ) -> None:
        """AC-18 residue: pre-existing rows with state=none + stamped
        frozen_at stay invisible — the renderer does not surface
        accepted residue."""
        conn = _connect(db_path)
        _seed_item(conn, 50, "Residue case")
        _set_field(conn, 50, "spec", "# Residue case\nContext body.")
        _set_field(conn, 50, "db_mutation_profile", '{"state":"none"}')
        _set_field(
            conn, 50, "db_compatibility_attestation",
            '{"frozen_at":"2026-04-23T22:01:29Z"}',
        )
        body = render_body.build_body(conn, 50) or ""
        conn.close()
        assert "## DB Claim" not in body
        assert "frozen_at" not in body

    def test_declared_profile_only_renders_claim_without_subsection(
        self, tmp_path: Path, db_path: str,
    ) -> None:
        conn = _connect(db_path)
        _seed_item(conn, 52, "Profile declared")
        _set_field(conn, 52, "spec", "# Profile declared\nContext body.")
        _set_field(conn, 52, "db_mutation_profile", self._declared_profile_json())
        body = render_body.build_body(conn, 52) or ""
        conn.close()
        assert "## DB Claim" in body
        assert "**State:** `declared`" in body
        assert "**Model:** `primary`" in body
        assert "**Intent:** `apply`" in body
        assert "**Compatibility class:** `pre_merge_safe`" in body
        assert "`add_items_due_date`" in body
        assert "`items` (columns: `due_date`)" in body
        assert "**Count preserving:** `true`" in body
        # No attestation seeded → no Safety attestation sub-heading.
        assert "### Safety attestation" not in body

    def test_declared_profile_with_attestation_renders_both_halves(
        self, tmp_path: Path, db_path: str,
    ) -> None:
        conn = _connect(db_path)
        _seed_item(conn, 53, "Claim full")
        _set_field(conn, 53, "spec", "# Claim full\nContext.")
        _set_field(conn, 53, "db_mutation_profile", self._declared_profile_json())
        _set_field(
            conn, 53, "db_compatibility_attestation",
            self._authored_attestation_json(),
        )
        body = render_body.build_body(conn, 53) or ""
        conn.close()
        # Single operator-facing heading — the historical names are gone.
        assert body.count("## DB Claim") == 1
        assert "DB Mutation Profile" not in body
        assert "DB Compatibility Attestation" not in body
        # Profile half present.
        assert "**State:** `declared`" in body
        assert "**Compatibility class:** `pre_merge_safe`" in body
        # Attestation half present under the sub-heading.
        assert "### Safety attestation" in body
        assert "**Frozen at:** `2026-04-22T17:52:49Z`" in body
        assert "runtime/api/domain/projects.py::load" in body
        assert "items.status values are drawn from canonical lifecycle" in body
        assert "python3 -m pytest runtime/api/domain/test_projects.py" in body
        assert "`pass` @ 2026-04-22T18:05:00Z" in body
        assert "**Residual risk notes:** Dashboard view one-cycle lag." in body
        assert "pre_merge_safe" in body and "pre_merge_breaking" in body
        assert "DROP TABLE detected" in body
        # Profile bullets must come before the attestation sub-heading.
        assert body.index("**State:** `declared`") < body.index(
            "### Safety attestation",
        )

    def test_declared_renders_between_design_and_technical(
        self, tmp_path: Path, db_path: str,
    ) -> None:
        conn = _connect(db_path)
        _seed_item(conn, 54, "Ordering test")
        conn.execute(
            "UPDATE items SET spec = %s, design_spec = %s, technical_plan = %s, "
            "db_mutation_profile = %s, db_compatibility_attestation = %s "
            "WHERE id = 54",
            (
                "# Ordering test\nIntro.",
                "Design body.",
                "Plan body.",
                self._declared_profile_json(),
                self._authored_attestation_json(),
            ),
        )
        conn.commit()
        body = render_body.build_body(conn, 54) or ""
        conn.close()
        design_idx = body.index("## Design Spec")
        claim_idx = body.index("## DB Claim")
        plan_idx = body.index("## Technical Plan")
        assert design_idx < claim_idx < plan_idx

    def test_unfrozen_authored_attestation_marks_pending(
        self, tmp_path: Path, db_path: str,
    ) -> None:
        """When the attestation carries authored fields without a freeze
        stamp (the pre-gate state), the Safety attestation sub-section
        renders with a 'not yet frozen' marker."""
        att_payload = json.dumps({
            "invariants": ["authored pre-gate"],
            "residual_risk_notes": "n/a",
        })
        conn = _connect(db_path)
        _seed_item(conn, 55, "Unfrozen attestation")
        _set_field(conn, 55, "spec", "# Unfrozen attestation\nContext.")
        _set_field(conn, 55, "db_mutation_profile", self._declared_profile_json())
        _set_field(conn, 55, "db_compatibility_attestation", att_payload)
        body = render_body.build_body(conn, 55) or ""
        conn.close()
        assert "## DB Claim" in body
        assert "### Safety attestation" in body
        assert "not yet frozen" in body
        assert "authored pre-gate" in body

    def test_malformed_profile_json_renders_nothing(self, tmp_path: Path, db_path: str) -> None:
        conn = _connect(db_path)
        _seed_item(conn, 56, "Malformed profile")
        _set_field(conn, 56, "spec", "# Malformed profile\nContext body.")
        _set_field(conn, 56, "db_mutation_profile", "{not json")
        body = render_body.build_body(conn, 56) or ""
        conn.close()
        assert "## DB Claim" not in body
        assert "Context body." in body

    def test_declared_profile_with_malformed_attestation_renders_profile_only(
        self, tmp_path: Path, db_path: str,
    ) -> None:
        """Malformed attestation JSON falls back to no sub-section, but
        the profile half of the claim still renders."""
        conn = _connect(db_path)
        _seed_item(conn, 57, "Mixed claim")
        _set_field(conn, 57, "spec", "# Mixed claim\nContext.")
        _set_field(conn, 57, "db_mutation_profile", self._declared_profile_json())
        _set_field(conn, 57, "db_compatibility_attestation", "{not json")
        body = render_body.build_body(conn, 57) or ""
        conn.close()
        assert "## DB Claim" in body
        assert "**State:** `declared`" in body
        assert "### Safety attestation" not in body
