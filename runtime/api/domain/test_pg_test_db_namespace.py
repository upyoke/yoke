"""Tests for owner-tagged test-database naming.

The grammar these tests pin is what keeps concurrent invocations from
touching each other's databases: names carry their creator's identity, and
every ownership decision downstream reads it back out of the name.
"""

from __future__ import annotations

import os

import pytest

from yoke_core.domain import pg_test_db_namespace as namespace
from yoke_core.domain.db_backend import POSTGRES_TEST_DB_PREFIX


@pytest.fixture(autouse=True)
def _unset_run_tag(monkeypatch):
    """Give each test a clean slate for the process-wide run tag."""
    monkeypatch.delenv(namespace.RUN_TAG_ENV, raising=False)


def test_run_tag_is_minted_once_and_published_for_child_processes():
    # xdist workers inherit the environment of the process that spawned them;
    # publishing the tag there is what makes a whole invocation share one owner.
    first = namespace.current_run_tag()

    assert namespace.current_run_tag() == first
    assert os.environ[namespace.RUN_TAG_ENV] == first


def test_run_tag_embeds_owner_pid(monkeypatch):
    monkeypatch.setenv(namespace.RUN_TAG_ENV, namespace.mint_run_tag(pid=4242))

    name = namespace.database_name("ambient_gw1")

    assert namespace.owner_pid_of(name) == 4242


def test_two_invocations_get_distinct_tags_even_with_one_pid():
    # PIDs are recycled; the random suffix is what keeps a reused PID from
    # making one invocation look like the owner of another's databases.
    first = namespace.mint_run_tag(pid=99)
    second = namespace.mint_run_tag(pid=99)

    assert first != second


def test_database_name_carries_prefix_tag_and_purpose(monkeypatch):
    monkeypatch.setenv(namespace.RUN_TAG_ENV, namespace.mint_run_tag(pid=7))

    name = namespace.database_name("template")

    assert name.startswith(POSTGRES_TEST_DB_PREFIX)
    assert name.endswith("_template")
    assert namespace.belongs_to_current_run(name)


def test_database_name_refuses_to_exceed_the_identifier_limit(monkeypatch):
    # PostgreSQL silently truncates past 63 bytes, which would collide two
    # databases whose names differ only in the truncated tail.
    monkeypatch.setenv(namespace.RUN_TAG_ENV, namespace.mint_run_tag(pid=1))

    with pytest.raises(ValueError, match="identifier limit"):
        namespace.database_name("x" * namespace.MAX_DATABASE_NAME_BYTES)


def test_another_invocations_database_is_not_ours(monkeypatch):
    monkeypatch.setenv(namespace.RUN_TAG_ENV, namespace.mint_run_tag(pid=11))
    theirs = f"{POSTGRES_TEST_DB_PREFIX}{namespace.mint_run_tag(pid=22)}_abc"

    assert namespace.owner_pid_of(theirs) == 22
    assert not namespace.belongs_to_current_run(theirs)


@pytest.mark.parametrize(
    "name",
    [
        # An operator's migration validation database: test-prefixed, but not
        # part of any invocation's namespace, so no sweep may ever claim it.
        f"{POSTGRES_TEST_DB_PREFIX}sun1234_validation",
        f"{POSTGRES_TEST_DB_PREFIX}runwithoutpid_abc",
        f"{POSTGRES_TEST_DB_PREFIX}run42x9f",  # no purpose segment
        "some_other_database",
    ],
)
def test_untagged_names_have_no_owner(name):
    assert namespace.run_tag_of(name) is None
    assert namespace.owner_pid_of(name) is None
    assert not namespace.belongs_to_current_run(name)


def test_owned_database_pattern_matches_only_tagged_names():
    assert namespace.OWNED_DATABASE_LIKE_PATTERN.startswith(
        POSTGRES_TEST_DB_PREFIX
    )
    assert namespace.OWNED_DATABASE_LIKE_PATTERN.endswith("%")
    assert namespace.RUN_TAG_MARKER in namespace.OWNED_DATABASE_LIKE_PATTERN
