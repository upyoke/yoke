"""Shared fixture builders for the ``test_qa_*`` split files.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports ``make_qa_db_file`` and ``make_basic_requirement`` and wraps them
in local ``@pytest.fixture`` shims (``with make_qa_db_file(tmp_path) as path:
yield path``), then re-exports ``Path`` and ``qa`` so the shape of imports
stays uniform across the family.

Distinct from ``qa_full_test_helpers`` which serves the broader ``test_qa_full*``
suite (different schema scaffolding and seed data). The two helper modules can
coexist; do not merge them.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from yoke_core.domain import qa
from runtime.api.fixtures.file_test_db import init_test_db


def _apply_qa_schema() -> None:
    """``apply_schema`` strategy building the QA schema via the backend factory.

    Builds the schema against the active Postgres authority.
    """
    qa.cmd_init()


@contextlib.contextmanager
def make_qa_db_file(tmp_path: Path):
    """Yield a backend-aware DB token with the QA tables initialised.

    Delegates to the ``file_test_db`` seam so the fixture gets a disposable
    per-test Postgres database, dropped on exit.
    Used as a context manager: ``with make_qa_db_file(tmp_path) as db_path:``.
    """
    with init_test_db(tmp_path, apply_schema=_apply_qa_schema) as db_path:
        yield db_path


def make_basic_requirement(db_path: str) -> int:
    """Create a basic ``unit_test`` / ``verification`` requirement.

    Returns the requirement ID used by tests that need one seeded row.
    """
    return qa.cmd_requirement_add(
        db_path=db_path,
        item_id=42,
        qa_kind="unit_test",
        qa_phase="verification",
    )


__all__ = [
    "make_qa_db_file",
    "make_basic_requirement",
    "Path",
    "qa",
]
