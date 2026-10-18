"""Reclaim only proven disposable test postmasters owned by this user."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from yoke_core.domain import postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec

MIN_IDLE_AGE_SECONDS = 15 * 60


def _postmasters() -> list[tuple[int, Path, Path]]:
    result = subprocess.run(
        ["ps", "-axo", "uid=,pid=,command="],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    found = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3 or fields[0] != str(os.getuid()):
            continue
        try:
            match = re.match(r"^(.*?)\s+-D\s+(.+?/data)(?=\s+-|$)", fields[2])
            if match is None:
                continue
            executable, directory = match.groups()
            binary = Path(executable)
            if binary.name not in {"postgres", "postmaster"}:
                continue
            data = Path(directory)
            if not binary.is_absolute():
                binary = Path(shutil.which(executable) or executable)
            found.append((int(fields[1]), data.parent, binary.parent))
        except (ValueError, IndexError):
            continue
    return found


def _spec(pid: int, root: Path, binaries: Path) -> tuple[ClusterSpec, float]:
    from yoke_core.tools.pg_testcluster import PGUSER

    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise ValueError("cluster root is not an owned real directory")
    data = root / "data"
    if data.is_symlink() or data.stat().st_uid != os.getuid():
        raise ValueError("cluster data is not an owned real directory")
    lines = (data / "postmaster.pid").read_text().splitlines()
    if int(lines[0]) != pid or Path(lines[1]).resolve() != data.resolve():
        raise ValueError("postmaster identity changed")
    return ClusterSpec(
        root=root,
        superuser=PGUSER,
        bin_dir=binaries,
        socket_dir=Path(lines[4]),
        stop_mode="immediate",
    ), float(lines[2])


def _idle(spec: ClusterSpec) -> bool:
    result = postgres_cluster._run(
        [
            postgres_cluster.binary(spec, "psql"),
            "-d",
            postgres_cluster.dsn(spec),
            "-Atc",
            f"SELECT current_user = '{spec.superuser}' AND NOT EXISTS "
            "(SELECT 1 FROM pg_stat_activity WHERE backend_type = 'client backend' "
            "AND pid <> pg_backend_pid())",
        ],
        timeout=5,
    )
    return result.returncode == 0 and result.stdout.strip() == "t"


def _stop(pid: int, spec: ClusterSpec) -> None:
    # Revalidate immediately before stopping; never unlink a live data directory.
    _spec(pid, spec.root, spec.bin_dir)
    result = postgres_cluster._run(
        [
            postgres_cluster.binary(spec, "pg_ctl"),
            "-D",
            str(spec.data_dir),
            "-m",
            "immediate",
            "-w",
            "-t",
            "10",
            "stop",
        ],
        timeout=15,
    )
    if result.returncode != 0 or (spec.data_dir / "postmaster.pid").exists():
        raise OSError(f"stop failed: {result.stderr.strip()}")


def _destroy(pid: int, spec: ClusterSpec) -> None:
    _stop(pid, spec)
    shutil.rmtree(spec.root)
    if not spec.sock_dir.is_relative_to(spec.root):
        try:
            spec.sock_dir.rmdir()
        except OSError:
            pass


def _reclaim(shared_root: Path | None, evidence: Path | None) -> int:
    failures = 0
    try:
        candidates = _postmasters()
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            f"pgtest_prune_unavailable: {exc}; restore ps access and retry prune-clusters",
            file=sys.stderr,
        )
        return 1
    for pid, root, binaries in candidates:
        canonical = root.resolve()
        if evidence is None and root.name != "yoke-pgtest-cluster":
            continue
        if shared_root is not None and canonical == shared_root.resolve():
            continue
        if evidence is not None and not canonical.is_relative_to(evidence.resolve()):
            continue
        try:
            spec, started = _spec(pid, root, binaries)
            if evidence is None and (
                time.time() - started < MIN_IDLE_AGE_SECONDS or not _idle(spec)
            ):
                continue
            if evidence is not None and canonical == evidence.resolve():
                _stop(pid, spec)
                shutil.rmtree(spec.data_dir)
                try:
                    spec.sock_dir.rmdir()
                except OSError:
                    pass
            else:
                _destroy(pid, spec)
            print(f"pgtest cluster reclaimed: {root}", file=sys.stderr)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
            failures += 1
            print(
                f"pgtest_cluster_reclaim_refused: root={root} pid={pid}: {exc}; "
                "inspect the named postmaster and retry prune-clusters after its clients exit",
                file=sys.stderr,
            )
    return 1 if failures else 0


def prune_clusters(shared_root: Path) -> int:
    """Keep the shared root, young postmasters and clusters with any clients."""
    return _reclaim(shared_root, None)


def destroy_evidence_clusters(evidence: Path) -> None:
    """A source command owns every disposable cluster inside its evidence root."""
    markers = list(evidence.glob("**/data/PG_VERSION"))
    if not markers:
        return
    failed = (
        _reclaim(None, evidence)
        if any((marker.parent / "postmaster.pid").exists() for marker in markers)
        else 0
    )
    for marker in markers:
        if not marker.is_file():
            continue
        root = marker.parent.parent
        if root.is_symlink() or marker.parent.is_symlink():
            continue
        if (marker.parent / "postmaster.pid").exists():
            failed = 1
            print(
                f"pgtest_evidence_postmaster_unresolved: {root}; preserve this evidence "
                "and stop the cluster with YOKE_PG_CLUSTER_ROOT set to this root "
                "using pg_testcluster stop, then retry cleanup",
                file=sys.stderr,
            )
        else:
            shutil.rmtree(marker.parent if root == evidence else root)
    if failed:
        raise OSError(
            f"pgtest_evidence_cleanup_failed: {evidence}; inspect the refusal above "
            "and stop the named cluster with pg_testcluster stop before deleting evidence"
        )
