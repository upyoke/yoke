"""Invocation totals, progress lines and the final prune summary."""

from collections import Counter
import json
import sys
import time

# A table that hits its statement/lock limit with a full pass budget is tried
# again on later cycles, at most this many times per invocation.
TABLE_SKIP_LIMIT = 3
PROGRESS_SECONDS = 10


def _duration(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


class PruneRun:
    """What one invocation has acknowledged across its passes."""

    def __init__(self, apply, clock=time.monotonic):
        self.apply = apply
        self.clock = clock
        self.started = clock()
        self.last_progress = self.started
        self.deleted = Counter()
        self.tables = {}
        self.skips = Counter()
        self.unfinished = {}
        self.finished = set()
        self.identity = {}
        self.cycle_deleted = 0
        self.cycle_retry = False

    def record(self, result):
        for row in result.get("tables", []):
            table = row["table"]
            self.tables[table] = row
            self.deleted.update(row["deleted"])
            self.cycle_deleted += sum(row["deleted"].values())
            self.unfinished.pop(table, None)
            if row["eligible"] == 0:
                self.finished.add(table)
        for skip in result.get("skipped", []):
            table = skip["table"]
            self.skips[table] += 1
            self.unfinished[table] = dict(skip, attempts=self.skips[table])
            if self.skips[table] < TABLE_SKIP_LIMIT:
                self.cycle_retry = True

    def next_cycle(self):
        """True when another cycle can still change something."""
        more = self.apply and (self.cycle_deleted > 0 or self.cycle_retry)
        self.cycle_deleted, self.cycle_retry = 0, False
        return more

    @property
    def skip_tables(self):
        spent = {t for t, n in self.skips.items() if n >= TABLE_SKIP_LIMIT}
        return sorted(self.finished | spent)

    def progress(self, stream=None):
        now = self.clock()
        if now - self.last_progress < PROGRESS_SECONDS:
            return
        self.last_progress = now
        open_tables = [
            t
            for t, row in self.tables.items()
            if row["eligible_partial"] and t not in self.finished
        ]
        largest = max(open_tables, key=lambda t: self.deleted[t], default=None)
        parts = [f"Pruning: {sum(self.deleted.values()):,} rows deleted"]
        if largest:
            parts.append(f"largest remaining: {largest}")
        parts.append(f"{_duration(now - self.started)} elapsed")
        print(" · ".join(parts), file=stream or sys.stderr, flush=True)

    def result(self, mode):
        result = dict(self.identity)
        result.update(
            mode=mode,
            deleted=dict(self.deleted),
            tables=list(self.tables.values()),
            unfinished=list(self.unfinished.values()),
            duration_seconds=round(self.clock() - self.started, 3),
        )
        return result


def write_summary(result, out, full):
    elapsed = _duration(result["duration_seconds"])
    if result["mode"] == "apply":
        changed = {t: n for t, n in result["deleted"].items() if n}
        print(f"Deleted {sum(changed.values()):,} rows in {elapsed}.", file=out)
        width = max((len(t) for t in changed), default=0)
        for table, count in sorted(changed.items(), key=lambda kv: -kv[1]):
            print(f"  {table:<{width}}  {count:>12,}", file=out)
    else:
        print(f"Preview only; nothing deleted ({elapsed}).", file=out)
        for row in result["tables"]:
            if row["eligible"]:
                bound = ">=" if row["eligible_partial"] else ""
                print(
                    f"  {row['table']}: {bound}{row['eligible']:,} eligible", file=out
                )
    if result["unfinished"]:
        print("Not finished:", file=out)
        for skip in result["unfinished"]:
            print(
                f"  {skip['table']} ({skip['code']}, {skip['attempts']} attempts): "
                f"{skip['reason']}. Recovery: {skip['recovery']}",
                file=out,
            )
    if full:
        _write_detail(result, out)
    elif result["mode"] != "apply":
        print(
            "Rerun with --apply to delete. Add --full for per-table detail.", file=out
        )


def _write_detail(result, out):
    identity = result.get("universe") or {}
    print(
        f"Universe {identity.get('slug')}; policy={result.get('policy_digest')}; cutoff={result.get('cutoff')}",
        file=out,
    )
    for row in result["tables"]:
        table = row["table"]
        eligible = (
            f">={row['eligible']} (bounded)"
            if row["eligible_partial"]
            else str(row["eligible"])
        )
        protected = (
            f"; protected>={row['protected']} (sample)"
            if row.get("protected") is not None
            else ""
        )
        deleted = result["deleted"].get(table, 0)
        print(f"{table}: eligible={eligible}; deleted={deleted}{protected}", file=out)
        if row.get("protected_graphs"):
            print(
                f"  retained graphs={row['protected_graphs']}: {row['graph_budget_reason']}",
                file=out,
            )
    print(
        "Committed deletion totals: " + json.dumps(result["deleted"], sort_keys=True),
        file=out,
    )
