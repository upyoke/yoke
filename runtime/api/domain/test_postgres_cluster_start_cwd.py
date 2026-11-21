"""The embedded Postgres server starts from its own root, never the caller's.

On Windows pg_ctl keeps a cmd.exe wrapper alive beside the server, holding
its starting directory. A hook that starts the universe database from inside
a lane would otherwise pin that lane until the server stops, and no merge
rerun or sweep could remove it.
"""

from __future__ import annotations

import subprocess

from yoke_core.domain import postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec


def test_server_start_runs_from_the_cluster_root(monkeypatch, tmp_path):
    lane = tmp_path / "repo" / ".worktrees" / "ITEM-1"
    lane.mkdir(parents=True)
    monkeypatch.chdir(lane)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(postgres_cluster, "_run", run)
    spec = ClusterSpec(root=tmp_path / "universe", superuser="yoke")
    postgres_cluster.start_server(spec)

    ((argv, kwargs),) = calls
    assert argv[-1] == "start"
    assert kwargs["cwd"] == str(spec.root)
