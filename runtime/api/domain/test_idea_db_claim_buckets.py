"""Skill-contract tests for the idea-phase DB-claim bucket discipline.

These tests pin the operator-facing prose for the three-bucket
classification (real-mutation-declare / real-mutation-blocker /
meta-ticket-reviewed-none) plus the Prevention 1 + 2 reference
verification rules. They are pure file-content assertions against the
live skill prose under ``.agents/skills/yoke/idea/`` — no DB, no
fixtures, no subprocess.

Failures here mean the operator-facing skill text drifted from the
canonical phrases the classifier, gate, and downstream tooling rely on.
The matched substrings are deliberately specific; small wording tweaks
that preserve the canonical signal can update both this test and the
skill prose in the same commit.
"""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BODY_AND_SYNC = _REPO_ROOT / ".agents/skills/yoke/idea/body-and-sync.md"
_INFER_AND_CREATE = _REPO_ROOT / ".agents/skills/yoke/idea/infer-and-create.md"
_OBSOLETED_DEFERRAL_REASON = "deferred declaration" + " to refine"


def _read(path: Path) -> str:
    assert path.exists(), f"missing skill file: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# body-and-sync.md — three-bucket discipline
# ---------------------------------------------------------------------------


class TestBodyAndSyncThreeBuckets:
    def test_no_db_work_canonical_reason_pinned(self):
        text = _read(_BODY_AND_SYNC)
        assert (
            'idea: spec/body declares no governed DB mutation' in text
        ), "Bucket-1 (no-DB) canonical reason text drifted."

    def test_meta_ticket_canonical_reason_pinned(self):
        text = _read(_BODY_AND_SYNC)
        assert (
            'idea: ticket discusses DB governance vocabulary but performs '
            'no governed DB mutation; reviewed-none' in text
        ), "Bucket-3 (meta-ticket) canonical reason text drifted."
        # The literal "; reviewed-none" suffix is the canonical signal.
        assert "; reviewed-none" in text

    def test_three_way_prompt_present(self):
        text = _read(_BODY_AND_SYNC)
        assert "Real governed mutation, declare now" in text
        assert "Real governed mutation, blocker for refine" in text
        assert "Meta-ticket about DB governance" in text

    def test_blocker_section_template_pinned(self):
        text = _read(_BODY_AND_SYNC)
        assert "## DB Claim Blocker (idea-time)" in text
        assert "Known facts:" in text
        assert "Missing facts that block declared payload:" in text

    def test_blocker_path_does_not_call_db_claim_amend(self):
        """Bucket-2 must NOT invoke db-claim-amend. The skill prose pins
        this with an explicit `Do NOT call db-claim-amend --state none`
        instruction so the schema default + missing event combo trips
        GATE_DB_CLAIM_PROSE_MISMATCH on the next advance."""
        text = _read(_BODY_AND_SYNC)
        # Locate the bucket-2 paragraph and assert the prohibition is
        # present nearby. The exact phrasing is operator-facing prose
        # but the imperative must survive any rewording.
        assert (
            "Do NOT call `db-claim-amend --state none`" in text
            or "Do NOT call `db-claim-amend`" in text
        )

    def test_bucket_discipline_rationale_present(self):
        """The skill explains why bucket discipline matters."""
        text = _read(_BODY_AND_SYNC)
        assert "Why bucket discipline matters" in text
        assert "validation_result" in text
        assert "reviewed-none" in text

    def test_obsoleted_deferral_reason_removed(self):
        """The retired deferral reason must not appear in this file."""
        text = _read(_BODY_AND_SYNC)
        assert _OBSOLETED_DEFERRAL_REASON not in text


# ---------------------------------------------------------------------------
# infer-and-create.md — Prevention 1 + 2
# ---------------------------------------------------------------------------


class TestInferAndCreatePreventions:
    def test_prevention_1_verification_verb_pinned(self):
        """Prevention 1 names ``test -d`` for directories and the
        Glob tool for file patterns."""
        text = _read(_INFER_AND_CREATE)
        assert "test -d" in text
        assert "Glob tool" in text or "Glob" in text

    def test_prevention_1_canonical_migration_root_named(self):
        """The live one-shot migration package root is named
        explicitly so future ideas don't propose the non-existent
        ``runtime/api/migrations/`` directory."""
        text = _read(_INFER_AND_CREATE)
        assert "runtime/api/domain/migrations/" in text

    def test_prevention_2_canonical_grep_template_pinned(self):
        """The canonical grep template is pinned literally so
        agents copy it directly rather than improvising."""
        text = _read(_INFER_AND_CREATE)
        assert (
            'rg -n "def _run_.*_gate|def check_.*_gate|GATE_[A-Z_]+" '
            "packages/ runtime/"
        ) in text

    def test_prevention_2_warns_against_lifecycle_py_intuition(self):
        """The common mistake (naming ``lifecycle.py`` for gate
        composition) must be called out so future agents recognize the
        anti-pattern in their own drafts."""
        text = _read(_INFER_AND_CREATE)
        assert "lifecycle.py" in text

    def test_duplicate_check_reads_board_and_recent_commits_first(self):
        """The idea duplicate pass must look at human-context surfaces
        before relying on literal phrase matching."""
        text = _read(_INFER_AND_CREATE)
        board_idx = text.index("sed -n '1,300p' .yoke/BOARD.md")
        commits_idx = text.index("git log --oneline -10")
        search_idx = text.index("items search")
        assert board_idx < search_idx
        assert commits_idx < search_idx
        assert "literal phrase matching" in text


# ---------------------------------------------------------------------------
# Repo-wide retired-prose residue grep
# ---------------------------------------------------------------------------


class TestObsoletedDeferralReasonResidue:
    def test_no_residue_in_skills_runtime_or_docs(self):
        """The old deferral reason must have no live residue."""
        roots = [
            _REPO_ROOT / ".agents" / "skills",
            _REPO_ROOT / "runtime",
            _REPO_ROOT / "docs",
        ]
        offenders = []
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.resolve() == Path(__file__).resolve():
                    continue
                # Skip binary files and large generated artifacts.
                if path.suffix in {".pyc", ".db", ".sqlite"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if _OBSOLETED_DEFERRAL_REASON in text:
                    offenders.append(str(path.relative_to(_REPO_ROOT)))
        assert offenders == [], (
            f"Obsoleted reason text {_OBSOLETED_DEFERRAL_REASON!r} "
            f"found in: {offenders}"
        )
