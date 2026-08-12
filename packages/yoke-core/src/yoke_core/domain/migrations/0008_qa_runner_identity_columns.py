"""Give the QA catalog its own word for what executes a case.

``executor`` named two unrelated things at once. On a harness session it is
the identity of the program driving the conversation — ``claude-code``,
``codex``, ``cursor`` — and that meaning is the one the vocabulary keeps.
On a QA method, requirement, or run it named something else entirely: which
runner carries the case out, and who or what produced a particular result.
One word answering both questions makes every reader of either surface stop
and work out which sense is in play, and makes a join across the two read as
though it relates things that have nothing to do with each other.

The QA sense is renamed to say what it is. ``qa_methods.runner_id`` and
``qa_requirements.runner_id`` carry the runner vocabulary
(``browser_substrate``, ``host_control``, ``worktree_run``, ``ci_run``);
``qa_methods.runner_gloss`` is that runner described in a phrase;
``qa_runs.performed_by`` records who or what actually produced the run,
which is why it is deliberately not a runner id — its values include
agents, humans, and CI systems as well as runners.

Every value is carried across unchanged. The one exception is the retired
default gloss text, which named the old vocabulary in prose a reader sees:
rows still carrying it move to the new default rather than keeping a phrase
that describes a concept the schema no longer has.
"""

from __future__ import annotations

from typing import Any

#: The oldest artifact that may serve a database this entry has been applied
#: to. Derived rather than chosen: every build carrying this code is newer
#: than ``0.1.1+launch.207``, the published build at authoring time, because
#: that build predates these commits and still reads all four columns under
#: their retired names. Build numbers only increase, so the shipping build is
#: at least ``launch.208``, which makes this floor low enough never to refuse
#: a build that can serve and high enough to refuse every build that cannot.
MINIMUM_SERVING_VERSION = "0.1.1+launch.208"

#: ``(table, retired column, current column)``. The retired names are the
#: entry's subject — it exists to remove them — so they appear here and
#: nowhere else in the live tree.
RENAMED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("qa_methods", "executor_id", "runner_id"),
    ("qa_methods", "executor_gloss", "runner_gloss"),
    ("qa_requirements", "executor_id", "runner_id"),
    ("qa_runs", "executor_type", "performed_by"),
)

#: The gloss a method falls back to when it names no runner of its own. The
#: retired text described the retired vocabulary, so rows carrying it are
#: moved rather than left naming a concept the schema dropped.
RETIRED_GLOSS_DEFAULT = "registered executor"
GLOSS_DEFAULT = "registered runner"


def apply(conn: Any) -> None:
    """Move each column to its current name, however far the database got.

    The boot converge adds strictly-additive columns before it applies this
    history, so a database can arrive here having already grown the current
    column as an empty one. That is not the same state as "already renamed",
    and a plain ``RENAME`` would fail against it. Where both names are
    present the retired column is the authority — the additive column was
    created moments earlier in the same boot — so its values are carried
    over and the retired column is dropped, which lands the same shape a
    rename would have. Where only the retired name is present the rename is
    the whole job, and where only the current name is present there is
    nothing left to do, which is what makes a replayed history harmless.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    for table, retired, current in RENAMED_COLUMNS:
        if not _table_exists(conn, table):
            continue
        if not _column_exists(conn, table, retired):
            continue
        if _column_exists(conn, table, current):
            conn.execute(
                f'UPDATE "{table}" SET "{current}" = "{retired}" '
                f'WHERE "{retired}" IS NOT NULL'
            )
            conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{retired}"')
            continue
        conn.execute(
            f'ALTER TABLE "{table}" '
            f'RENAME COLUMN "{retired}" TO "{current}"'
        )

    if not _table_exists(conn, "qa_methods"):
        return
    if not _column_exists(conn, "qa_methods", "runner_gloss"):
        return
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE qa_methods SET runner_gloss = {marker} "
        f"WHERE runner_gloss = {marker}",
        (GLOSS_DEFAULT, RETIRED_GLOSS_DEFAULT),
    )
    if db_backend.connection_is_postgres(conn):
        # A renamed column keeps the default it was created with, so without
        # this a converged database and a freshly created one disagree on
        # what an unspecified gloss becomes. SQLite cannot alter a default in
        # place; its databases are validation surfaces that are recreated
        # from current DDL rather than long-lived universes.
        conn.execute(
            "ALTER TABLE qa_methods "
            f"ALTER COLUMN runner_gloss SET DEFAULT '{GLOSS_DEFAULT}'"
        )


def invariants(conn: Any) -> None:
    """Prove no retired column survives and every current one is present.

    Both halves matter. A surviving retired column means a reader can still
    find the old vocabulary; a missing current column means the rename lost
    the surface its readers now require, which on ``qa_runs`` would be every
    QA verdict the universe has recorded.
    """
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    for table, retired, current in RENAMED_COLUMNS:
        if not _table_exists(conn, table):
            continue
        if _column_exists(conn, table, retired):
            raise AssertionError(
                f"{table}.{retired} is retired but still present; "
                f"{table}.{current} is the current name"
            )
        if not _column_exists(conn, table, current):
            raise AssertionError(
                f"{table}.{current} is required but absent"
            )


__all__ = [
    "GLOSS_DEFAULT",
    "MINIMUM_SERVING_VERSION",
    "RENAMED_COLUMNS",
    "RETIRED_GLOSS_DEFAULT",
    "apply",
    "invariants",
]
