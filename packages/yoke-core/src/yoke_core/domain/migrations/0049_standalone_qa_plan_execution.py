"""Admit standalone plan executions without changing existing gate owners."""

from yoke_core.domain.qa_standalone_schema import (
    assert_standalone_subjects,
    replace_standalone_subjects,
)

MINIMUM_SERVING_VERSION = "next-release"
RETIRES_INVARIANTS = ("0043_scoped_deployment_qa_execution",)


def apply(conn):
    replace_standalone_subjects(conn)


def invariants(conn):
    assert_standalone_subjects(conn)
