"""Operation-scoped repository facts, with current attribution read separately."""

from yoke_core.domain.deployment_source_reads import source_read
from yoke_core.domain.deployment_run_carried_work_source import open_carried_work_source


def prepared_carried_work_source(conn, project_id, repo_root=None):
    key = ("carried_source", int(project_id), str(repo_root or ""))
    return source_read(
        conn,
        key,
        lambda: PreparedSource(
            conn,
            key,
            open_carried_work_source(
                conn,
                project_id,
                repo_root=repo_root,
            ),
        ),
    )


class PreparedSource:
    """Cache repository reads, never item/workflow/membership/evidence answers."""

    def __init__(self, conn, key, source):
        self.conn, self.key, self.source = conn, key, source
        self.origin, self.location = source.origin, source.location

    def _read(self, method, *args, **kwargs):
        key = (*self.key, method, args, tuple(sorted(kwargs.items())))
        return source_read(
            self.conn,
            key,
            lambda: getattr(self.source, method)(*args, **kwargs),
        )

    def resolve_commit(self, ref):
        return self._read("resolve_commit", ref)

    def resolve_commits(self, refs):
        # Preparation and locked validation read the same lane rows in no
        # fixed order, so the question is the ref set, never the row order.
        return self._read("resolve_commits", tuple(sorted(set(refs))))

    def lineage_relation(self, base, head):
        return self._read("lineage_relation", base, head)

    def commit_range(self, base, head):
        return self._read("commit_range", base, head)

    def commit_message(self, sha):
        return self._read("commit_message", sha)

    def commit_time(self, sha):
        return self._read("commit_time", sha)

    def commit_author(self, sha):
        return self._read("commit_author", sha)

    def carrying_commit(self, lane_commit, *, base, head, commits):
        return self._read(
            "carrying_commit",
            lane_commit,
            base=base,
            head=head,
            commits=tuple(commits),
        )

    def contains_commit(self, candidate, commit):
        return self._read("contains_commit", candidate, commit)

    def adds_nothing(self, candidate, commit):
        return self._read("adds_nothing", candidate, commit)

    def warnings(self):
        return self.source.warnings()
