"""Discover real scoped partition keys for admission tests."""

from yoke_core.domain.qa_plan_execution_store import build_execution_roster
from yoke_core.domain.qa_plan_partition_custody import PartitionScope
from yoke_core.domain.qa_plan_partitions import scoped_partition_views


def scoped_partitions(conn, **subject):
    scope = PartitionScope(**subject)
    return scoped_partition_views(conn, scope, build_execution_roster(conn, **subject))
