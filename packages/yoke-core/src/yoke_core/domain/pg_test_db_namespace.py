"""Owner-tagged naming for disposable Postgres test databases.

One shared per-user cluster serves every concurrent pytest invocation on a
machine: databases are cheap, while a full ``initdb`` per ad hoc run would
tax iteration latency. Safety at any concurrency therefore comes from the
NAME, not from the cluster topology — every database an invocation creates
carries that invocation's run tag, and an invocation may only ever drop
databases carrying its own tag.

The run tag is minted once per invocation and published through
:data:`RUN_TAG_ENV` so pytest-xdist workers, which inherit the environment
from the process that spawned them, share the tag of the invocation they
belong to. The tag embeds the minting process's PID so an orphan sweep can
ask the operating system whether the owner is still alive; the random
suffix keeps two invocations distinct even when a PID is recycled.

Name grammar::

    yoke_test_run<pid>x<random>_<purpose>
    ^^^^^^^^^^                              shared test-database prefix
              ^^^^^^^^^^^^^^^                run tag (owner identity)
                              ^^^^^^^^^      caller-supplied purpose

Names that do not match the run-tag grammar — an operator's migration
validation database, for instance — are outside this namespace entirely and
no invocation may reap them.

*Where* a name in this namespace may be created is a separate question with a
separate answer: :mod:`yoke_core.domain.scratch_database_authority` refuses
the whole namespace on a cluster this machine only administers, so a run that
inherited a prod connection cannot leave strays on it.
"""

from __future__ import annotations

import os
import re
import uuid

from yoke_core.domain.db_backend import POSTGRES_TEST_DB_PREFIX
from yoke_core.domain.scratch_database_authority import (
    refuse_scratch_database_on_administered_cluster,
)

#: Environment variable carrying the current invocation's run tag. Set by the
#: first process in an invocation to ask for a tag; inherited by xdist workers.
RUN_TAG_ENV = "YOKE_TEST_RUN_TAG"

#: Leading token that marks a database name as owner-tagged. Databases without
#: it are not part of any invocation's namespace and are never swept.
RUN_TAG_MARKER = "run"

#: PostgreSQL truncates identifiers past this many bytes, which would silently
#: collide two databases whose names differ only in a truncated suffix.
MAX_DATABASE_NAME_BYTES = 63

_RANDOM_SUFFIX_HEX_CHARS = 6

_RUN_TAG_RE = re.compile(
    rf"^{re.escape(RUN_TAG_MARKER)}(?P<pid>\d+)x(?P<random>[0-9a-f]+)$"
)

#: Leading token every owner-tagged scratch database name carries. Reserved:
#: a database whose name starts with it is disposable by construction, so no
#: fleet, inventory, or rehearsal may treat one as a member.
SCRATCH_DATABASE_PREFIX = f"{POSTGRES_TEST_DB_PREFIX}{RUN_TAG_MARKER}"

#: SQL ``LIKE`` pattern selecting every owner-tagged test database.
OWNED_DATABASE_LIKE_PATTERN = f"{SCRATCH_DATABASE_PREFIX}%"


def mint_run_tag(pid: int | None = None) -> str:
    """Return a fresh owner tag for the calling process."""
    owner = os.getpid() if pid is None else pid
    random_suffix = uuid.uuid4().hex[:_RANDOM_SUFFIX_HEX_CHARS]
    return f"{RUN_TAG_MARKER}{owner}x{random_suffix}"


def current_run_tag() -> str:
    """Return this invocation's run tag, minting and publishing it once.

    ``setdefault`` is the whole coordination mechanism: the first process to
    ask publishes the tag into the environment, and every process it later
    spawns — xdist workers above all — inherits the same answer. A worker that
    somehow starts without the variable mints its own tag rather than failing;
    it then owns a namespace of one, which is narrower but never unsafe.
    """
    return os.environ.setdefault(RUN_TAG_ENV, mint_run_tag())


def database_name(purpose: str) -> str:
    """Return an owner-tagged database name for *purpose*.

    Every creator of a scratch database passes through here, because a name
    without this invocation's run tag is refused by every ownership check
    downstream. That makes this the one place where the cluster the name is
    destined for can be judged, so the refusal in
    :mod:`yoke_core.domain.scratch_database_authority` lives here and a
    creator added later inherits it without knowing it exists.

    Raises when the composed name would exceed PostgreSQL's identifier limit,
    since silent truncation is how two distinct databases become one.
    """
    name = f"{POSTGRES_TEST_DB_PREFIX}{current_run_tag()}_{purpose}"
    refuse_scratch_database_on_administered_cluster(name)
    if len(name.encode("utf-8")) > MAX_DATABASE_NAME_BYTES:
        raise ValueError(
            f"test database name {name!r} exceeds PostgreSQL's "
            f"{MAX_DATABASE_NAME_BYTES}-byte identifier limit; shorten the "
            f"purpose segment {purpose!r}"
        )
    return name


def run_tag_of(name: str) -> str | None:
    """Return the run tag embedded in *name*, or None when it carries none."""
    if not name.startswith(POSTGRES_TEST_DB_PREFIX):
        return None
    remainder = name[len(POSTGRES_TEST_DB_PREFIX) :]
    tag, separator, _ = remainder.partition("_")
    if not separator:
        return None
    return tag if _RUN_TAG_RE.match(tag) else None


def owner_pid_of(name: str) -> int | None:
    """Return the PID that owns *name*, or None when *name* is not owner-tagged."""
    tag = run_tag_of(name)
    if tag is None:
        return None
    match = _RUN_TAG_RE.match(tag)
    assert match is not None  # run_tag_of only returns matching tags
    return int(match.group("pid"))


def belongs_to_current_run(name: str) -> bool:
    """Return true when *name* was created by this invocation."""
    return run_tag_of(name) == current_run_tag()


__all__ = [
    "MAX_DATABASE_NAME_BYTES",
    "OWNED_DATABASE_LIKE_PATTERN",
    "RUN_TAG_ENV",
    "RUN_TAG_MARKER",
    "SCRATCH_DATABASE_PREFIX",
    "belongs_to_current_run",
    "current_run_tag",
    "database_name",
    "mint_run_tag",
    "owner_pid_of",
    "run_tag_of",
]
