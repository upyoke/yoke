"""The run fingerprint one QA write reads before the run row lock."""

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_run_qa_fingerprint import run_qa_fingerprint


class MaterializationProjection:
    """The run's QA fingerprint and members, read once before the run lock.

    The fingerprint comes first, so ``holds`` under the run lock proves every
    later unlocked read of the run is still current.
    """

    def __init__(self, conn, run_id):
        self.conn = conn
        self.run_id = str(run_id)
        self.fingerprint = run_qa_fingerprint(conn, self.run_id)
        self._members = None

    def holds(self, conn) -> bool:
        """Whether nothing this projection read changed; call under the run lock."""
        return run_qa_fingerprint(conn, self.run_id) == self.fingerprint

    def members(self):
        if self._members is None:
            self._members = query_rows(
                self.conn,
                "SELECT m.item_id,m.requirement_snapshot,i.project_id "
                "FROM deployment_run_items m JOIN items i ON i.id=m.item_id "
                "WHERE m.run_id=%s ORDER BY m.item_id",
                (self.run_id,),
            )
        return self._members
