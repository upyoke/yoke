# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.conftest import insert_epic_task, insert_item

from yoke_core.domain import epic

RECEIPT = """Progress note text.

---SUBMISSION-CHECKS-START---
test_plan: PASS - pytest passed
files_touched: PASS - checked files
edited_tests: SKIP - no tests edited
clean_worktree: PASS - git status --porcelain is empty
progress_notes: PASS - note written
file_budget: PASS - files under limit
---SUBMISSION-CHECKS-END---
"""
