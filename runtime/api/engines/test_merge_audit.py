"""Tests for yoke_core.engines.merge_audit report generation.

Git helper and CLI tests live in test_merge_audit_helpers.py.
"""

from __future__ import annotations

import sys
import os
import subprocess

from runtime.api.engines.merge_audit_test_seeds import (
    seed_merge_audit_item,
    seed_merge_audit_task,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.engines.merge_audit_full_test_support import (
    _add_branch,
    fake_repo as fake_repo,
    tmp_db as tmp_db,
)
from runtime.api.source_pythonpath_test_helpers import SOURCE_PYTHONPATH


class TestGenerateReport:
    """Test report generation with mock git state."""


    def test_exit_code_always_zero(self, tmp_db, fake_repo):
        """CLI exits 0 even when there are warnings."""
        conn = connect_test_db(tmp_db)
        seed_merge_audit_item(conn, item_id=800, title="Ex", status="implementing")
        seed_merge_audit_task(
            conn,
            epic_id=800,
            task_num=1,
            title="T1",
            status="planned",
            branch="YOK-800",
        )
        conn.commit()
        conn.close()

        _add_branch(fake_repo, "YOK-800")

        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.engines.merge_audit", "YOK-800"],
            capture_output=True,
            text=True,
            cwd=str(fake_repo),
            env={
                **os.environ,
                "YOKE_DB": tmp_db,
                "MERGE_AUDIT_REPO_ROOT": fake_repo,
                "PYTHONPATH": SOURCE_PYTHONPATH,
            },
        )
        assert result.returncode == 0
