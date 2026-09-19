"""``--head-only`` records the head it names and reads nothing else."""

from __future__ import annotations

from pathlib import Path

from runtime.api.cli.project_snapshot_cli_test_helpers import (
    CALLS as _CALLS,
    make_repo as _make_repo,
    run_cli as _run,
)


def test_head_only_records_the_head_without_scanning_the_tree(
    tmp_path: Path,
) -> None:
    """The flag names HEAD's identity, and that is all it reads.

    Scanning every blob anyway made the fast stale-lane-head re-stamp a full
    upload: it outran the relay's time limit and exited non-zero, while the
    head it names had already been recorded — so the one documented recovery
    looked like it had failed.
    """
    repo = _make_repo(tmp_path)
    rc, _out, err = _run(
        "project",
        "snapshot",
        "sync",
        str(repo),
        "--project",
        "demo",
        "--head-only",
    )

    assert rc == 0
    assert "identity only" in err
    payload = _CALLS[-1]["payload"]
    assert len(payload["snapshots"]) == 1
    assert payload["snapshots"][0]["files"] == []
