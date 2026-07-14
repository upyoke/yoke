"""Unified per-commit cache for board velocity widgets.

One ``git log --all --numstat`` per repo populates a hash-keyed cache
that captures total lines and commit metadata. The activity sparkline,
the streak/lifetime metric, and the git-derived velocity-meter rows all
read from this single cache; warm rebuilds hit memory only after the
first call within a process.
"""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Cap the on-disk cache horizon. Large enough to cover most project
# ages; entries older than this fall off.
_PRUNE_DAYS = 730  # 2 years

_CACHE_BASENAME = ".commit-cache.json"
_LIST_TIMEOUT_SECONDS = 2
# Warm path: only the handful of new commits since the last refresh, so a
# tight bound is correct (a slow warm walk signals a problem).
_POPULATE_TIMEOUT_SECONDS = 3
# Cold path: a from-empty `--numstat` walk over the full prune horizon. On a
# large repo (tens of thousands of commits) this legitimately takes seconds;
# a tight bound silently zeroed the repo out of the cache. Cold populate runs
# ~once per machine, off the warm hot path, so a generous bound is cheap.
_BULK_POPULATE_TIMEOUT_SECONDS = 30
_META_KEY = "__meta__"
_STALE_OK_SECONDS = 60

# In-process memo so multiple callers within a single rebuild share work.
_memo: Dict[Tuple[str, ...], Dict[str, Dict]] = {}


def _load_cache_file(cache_path: Path) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    if not cache_path.exists():
        return {}, {}
    try:
        raw = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}, {}
    if not isinstance(raw, dict):
        return {}, {}
    meta_raw = raw.pop(_META_KEY, {})
    meta = meta_raw if isinstance(meta_raw, dict) else {}
    cache = {
        str(h): e for h, e in raw.items()
        if isinstance(e, dict) and isinstance(h, str)
    }
    return cache, meta


def _cache_file_payload(
    cache: Dict[str, Dict], meta: Dict[str, Dict],
) -> Dict[str, Dict]:
    payload: Dict[str, Dict] = dict(cache)
    payload[_META_KEY] = meta
    return payload


def _repo_fresh(repo: str, meta: Dict[str, Dict], now: float) -> bool:
    entry = meta.get(repo)
    if not isinstance(entry, dict):
        return False
    try:
        checked_at = float(entry.get("checked_at") or 0)
    except (TypeError, ValueError):
        return False
    return (now - checked_at) < _STALE_OK_SECONDS


def _cache_path() -> Path:
    from yoke_contracts.machine_config import runtime as machine_config

    return machine_config.cache_dir() / _CACHE_BASENAME


def get_commit_data(repos: List[str]) -> Dict[str, Dict]:
    """Return the per-hash commit cache for *repos*.

    Cache entries: ``{hash: {day, lines, repo}}``.
    Memoized per process by ``sorted(repos)`` so the sparkline,
    streak, lifetime, and velocity-meter widgets all share one fetch.
    """
    if not repos:
        return {}
    key = tuple(sorted(repos))
    if key in _memo:
        return _memo[key]

    cache_path = _cache_path()
    cache, meta = _load_cache_file(cache_path)

    since_date = (date.today() - timedelta(days=_PRUNE_DAYS)).isoformat()
    repo_has_existing = {
        repo: any(e.get("repo") == repo for e in cache.values()) for repo in repos
    }
    now = time.time()
    if all(repo_has_existing.get(repo) and _repo_fresh(repo, meta, now)
           for repo in repos):
        _memo[key] = cache
        return cache

    def _refresh(repo: str) -> Dict[str, Dict]:
        # Cache entries to merge back into the parent cache. Each repo
        # builds its own slice so the parallel workers don't write to
        # the same dict concurrently.
        slice_cache: Dict[str, Dict] = {
            h: e for h, e in cache.items() if e.get("repo") == repo
        }
        try:
            listing = subprocess.run(
                ["git", "-C", repo, "log", "--all",
                 f"--since={since_date}", "--format=%H"],
                capture_output=True, text=True, timeout=_LIST_TIMEOUT_SECONDS,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return slice_cache
        if listing.returncode != 0:
            return slice_cache
        meta[repo] = {"checked_at": now}
        repo_hashes = [h for h in listing.stdout.split() if h]
        unknown = [h for h in repo_hashes if h not in slice_cache]
        if not unknown:
            return slice_cache
        # Warm (a few new commits) → cheap ``--no-walk`` over just the
        # unknown hashes. Cold → bulk-walk since *since_date*.
        if repo_has_existing[repo]:
            _populate_specific(repo, unknown, slice_cache)
        else:
            _bulk_populate(repo, since_date, slice_cache)
        return slice_cache

    has_new = False
    touched_meta = False
    with ThreadPoolExecutor(max_workers=max(len(repos), 1)) as pool:
        for repo, fresh_slice in zip(repos, pool.map(_refresh, repos)):
            if repo in meta:
                touched_meta = True
            for h, entry in fresh_slice.items():
                if h not in cache:
                    cache[h] = entry
                    has_new = True

    if has_new or touched_meta:
        cache = {h: e for h, e in cache.items() if e.get("day", "") >= since_date}
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(_cache_file_payload(cache, meta)))
        except OSError:
            pass

    _memo[key] = cache
    return cache


def _populate_specific(
    repo: str, hashes: List[str], cache: Dict[str, Dict],
) -> None:
    """Populate *cache* with exactly the given *hashes* via ``--no-walk``."""
    if not hashes:
        return
    try:
        result = subprocess.run(
            ["git", "-C", repo, "log", "--no-walk",
             "--format=COMMIT %H %ad", "--date=short", "--numstat",
             *hashes],
            capture_output=True, text=True, timeout=_POPULATE_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return
    if result.returncode != 0:
        return
    _ingest_numstat(repo, result.stdout, cache)


def _bulk_populate(repo: str, since_date: str, cache: Dict[str, Dict]) -> None:
    """Populate *cache* with all *repo* commits since *since_date*."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "log", "--all", f"--since={since_date}",
             "--format=COMMIT %H %ad", "--date=short", "--numstat"],
            capture_output=True, text=True,
            timeout=_BULK_POPULATE_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return
    if result.returncode != 0:
        return
    _ingest_numstat(repo, result.stdout, cache)


def _ingest_numstat(repo: str, stdout: str, cache: Dict[str, Dict]) -> None:
    """Parse ``git log --numstat`` output and add new commits to *cache*."""
    current_hash: Optional[str] = None
    current_day: Optional[str] = None
    current_lines = 0

    def flush() -> None:
        if current_hash and current_hash not in cache:
            cache[current_hash] = {
                "day": current_day,
                "lines": current_lines,
                "repo": repo,
            }

    for line in stdout.splitlines():
        if line.startswith("COMMIT "):
            flush()
            parts = line.split(" ", 2)
            current_hash = parts[1] if len(parts) > 1 else None
            current_day = parts[2] if len(parts) > 2 else None
            current_lines = 0
            continue
        if not current_hash or "\t" not in line:
            continue
        added, deleted, path = line.split("\t", 2)
        if path.endswith(".csv"):
            continue
        if added.isdigit() and deleted.isdigit():
            current_lines += int(added) + int(deleted)
    flush()


def _per_day(
    repos: List[str], days: int, field: Optional[str],
) -> Dict[str, int]:
    """Bucket cache entries by day, summing *field* (or 1 if None)."""
    cache = get_commit_data(repos)
    if not cache:
        return {}
    since_date = (date.today() - timedelta(days=days)).isoformat()
    repo_set = set(repos)
    counts: Dict[str, int] = {}
    for entry in cache.values():
        if entry.get("repo") not in repo_set:
            continue
        day = entry.get("day", "")
        if not day or day < since_date:
            continue
        n = 1 if field is None else int(entry.get(field, 0) or 0)
        if n > 0:
            counts[day] = counts.get(day, 0) + n
    return counts


def commits_per_day(repos: List[str], days: int) -> Dict[str, int]:
    """Per-day commit count over the last *days* days."""
    return _per_day(repos, days, None)


def lines_per_day(repos: List[str], days: int) -> Dict[str, int]:
    """Per-day total line changes over the last *days* days."""
    return _per_day(repos, days, "lines")


def _reset_memo_for_tests() -> None:
    """Clear the per-process memo. Test-only hook."""
    _memo.clear()
