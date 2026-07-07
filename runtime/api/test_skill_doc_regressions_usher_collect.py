"""Doc regression: usher collect Step 3b must scope to ``integration``.

Collect is the pre-merge integration gate. Calling
``python3 -m yoke_core.domain.check_hard_blocks`` without the
``--gate-point integration`` flag asks the all-gates question and
falsely flags ``coordination_only`` and already-satisfied
``activation`` edges as merge blockers. This regression test pins
Step 3b's invocation shape so the failure mode from theincident cluster (collect blocking when
``check_hard_blocks --gate-point integration`` returned success in
isolation) cannot regress.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    SKILLS,
    _read,
)


_COLLECT_PATH = SKILLS / "usher" / "collect.md"

# Match real invocations of ``check_hard_blocks`` at the start of a line
# (optionally preceded by ``if `` or whitespace). Prose mentions inside
# inline code fences or descriptive sentences do not count.
_INVOCATION_RE = re.compile(
    r"^\s*(?:if\s+)?python3\s+-m\s+runtime\.api\.domain\.check_hard_blocks\b"
)


class TestUsherCollectIntegrationGate:
    @pytest.fixture
    def collect_text(self) -> str:
        assert _COLLECT_PATH.is_file(), f"missing {_COLLECT_PATH}"
        return _read(_COLLECT_PATH)

    def test_collect_invokes_check_hard_blocks_with_gate_point_integration(
        self, collect_text: str,
    ):
        # Step 3b must spell ``--gate-point integration``.
        assert "--gate-point integration" in collect_text, (
            "usher/collect.md missing --gate-point integration in Step 3b"
        )

    def test_collect_has_no_unscoped_check_hard_blocks_call(
        self, collect_text: str,
    ):
        # Every real invocation of ``check_hard_blocks`` in the
        # collect skill body must carry a ``--gate-point`` flag.
        unscoped: list[str] = []
        for line in collect_text.splitlines():
            if _INVOCATION_RE.search(line) and "--gate-point" not in line:
                unscoped.append(line.strip())
        assert not unscoped, (
            "unscoped check_hard_blocks invocation(s) found in "
            "usher/collect.md; all must use --gate-point: " + repr(unscoped)
        )

    def test_collect_describes_integration_gate_intent(
        self, collect_text: str,
    ):
        # The prose must teach the gate-point intent so a future doc
        # author does not accidentally drop the flag thinking the
        # all-gates check is broader / safer.
        assert "integration" in collect_text.lower()
        assert "coordination_only" in collect_text or "coordination-only" in collect_text, (
            "usher/collect.md must explain why coordination_only rows are "
            "not merge blockers at the integration gate"
        )
