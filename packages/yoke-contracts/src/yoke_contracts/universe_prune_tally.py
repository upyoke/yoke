"""What one prune invocation has acknowledged across its stateless passes.

The foreground ``yoke universe prune`` command and control-plane upkeep's
scheduled prune drive the same pass loop, so both keep their totals, finished
tables and limit retries here.
"""

from collections import Counter

# A table that hits its statement/lock limit with a full pass budget is tried
# again on later cycles; it stops after this many limit hits in a row. A
# cohort that deletes rows resets the count, so a busy table still drains,
# and the total stays bounded because every reset needs a deletion.
TABLE_SKIP_LIMIT = 3


class PruneTally:
    """Deleted rows, finished tables and limit hits across passes."""

    def __init__(self, apply):
        self.apply = apply
        self.deleted = Counter()
        self.tables = {}
        self.skips = Counter()
        self.unfinished = {}
        self.finished = set()
        self.cycle_deleted = 0
        self.cycle_retry = False

    def record(self, result):
        for row in result.get("tables", []):
            table = row["table"]
            self.tables[table] = row
            self.deleted.update(row["deleted"])
            self.cycle_deleted += sum(row["deleted"].values())
            self.unfinished.pop(table, None)
            if any(row["deleted"].values()):
                self.skips.pop(table, None)
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


__all__ = ["PruneTally", "TABLE_SKIP_LIMIT"]
