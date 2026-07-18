"""Doc regressions: entry-activation.md S3b claim-verification contract.

Verifies that entry-activation.md S3b:
  (a) does NOT swallow session-touch stderr (no >/dev/null on stderr)
  (b) includes a post-claim-work active-claim verification block
  (c) uses the canonical diagnostic read adapter (not a raw DB path or
      worktree path)
"""

from __future__ import annotations

import os
import unittest

_SKILL_ROOT = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    ".agents",
    "skills",
    "yoke",
    "conduct",
    "entry-activation.md",
)


def _read_s3b() -> str:
    path = os.path.normpath(_SKILL_ROOT)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    # Extract from S3b heading to the next ### heading
    start = text.find("### S3b.")
    if start == -1:
        return ""
    end = text.find("\n### ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class TestEntryActivationS3bContract(unittest.TestCase):

    def setUp(self) -> None:
        self.s3b = _read_s3b()
        self.assertNotEqual(self.s3b, "", "S3b section not found in entry-activation.md")

    def test_session_touch_stderr_not_swallowed(self) -> None:
        """session-touch stderr must not be redirected to /dev/null."""
        # The bad pattern is: session-touch ... >/dev/null 2>&1
        # The good pattern exposes stderr: 2>&1 || true  OR just || true
        self.assertNotIn(
            ">/dev/null 2>&1",
            self.s3b,
            "S3b must not swallow session-touch stderr with >/dev/null 2>&1",
        )

    def test_post_claim_verification_present(self) -> None:
        """S3b must include a post-claim-work active-claim verification step."""
        # Look for the DB query pattern that verifies an active claim exists
        self.assertIn(
            "work_claims",
            self.s3b,
            "S3b must include a work_claims verification query after claim-work",
        )
        self.assertIn(
            "released_at IS NULL",
            self.s3b,
            "S3b verification must check released_at IS NULL to confirm active claim",
        )

    def test_halt_on_verification_failure(self) -> None:
        """S3b must HALT when the active-claim verification fails."""
        self.assertIn(
            "HALT",
            self.s3b,
            "S3b must include a HALT directive when claim verification fails",
        )

    def test_uses_canonical_db_read(self) -> None:
        """S3b verification uses the registered diagnostic-read adapter."""
        self.assertIn(
            "yoke db read",
            self.s3b,
            "S3b must use yoke db read for claim verification",
        )
        self.assertNotIn(
            "db_router",
            self.s3b,
            "S3b must not teach the operator-debug DB router as agent default",
        )
        # Must not construct a path to yoke.db or .worktrees/*/data/
        self.assertNotIn(
            "yoke.db",
            self.s3b,
            "S3b must not reference yoke.db directly",
        )
        self.assertNotIn(
            ".worktrees/",
            self.s3b,
            "S3b must not reference .worktrees/ paths for DB access",
        )


class TestEntryActivationTeachesFunctionCallAdapters(unittest.TestCase):
    """Conduct entry activation teaches function-call adapters.

    Entry activation is the canonical surface for the
    ``claims.work.claim`` function family — it always pairs
    ``session-touch`` and ``claim-work`` in the same step. The
    assertions encode the function-call adapter expectations.
    """

    def setUp(self) -> None:
        self.s3b = _read_s3b()
        self.assertNotEqual(
            self.s3b, "",
            "S3b section not found in entry-activation.md",
        )

    def test_s3b_does_not_teach_explicit_session_touch(self) -> None:
        """Session presence is auto-handled by the
        harness session hooks, so agents are not told to call it manually
        before claim-work. Anti-regression guard (claim acquire itself is
        covered by test_s3b_teaches_claim_work_adapter)."""
        self.assertNotIn(
            "session-touch",
            self.s3b,
            "S3b should NOT teach a manual session-touch step — session "
            "presence is auto-handled by the harness session hooks.",
        )

    def test_s3b_teaches_claim_work_adapter(self) -> None:
        """claim-work dispatches through ``claims.work.claim`` — it is
        the canonical work-claim acquisition adapter."""
        self.assertIn(
            "claim-work",
            self.s3b,
            "S3b must teach claim-work (function id: "
            "claims.work.claim).",
        )

    def test_s3b_recovery_hint_names_claim_work_adapter(self) -> None:
        """The S3b failure recovery hint must name the same adapter the
        skill teaches so the operator/agent can self-recover without
        consulting external docs."""
        self.assertIn(
            "yoke claims work acquire",
            self.s3b,
            "S3b recovery hint must name "
            "``yoke claims work acquire`` so the canonical agent CLI "
            "adapter is the obvious next step.",
        )


if __name__ == "__main__":
    unittest.main()
