"""The ordered migration history for the Yoke control-plane schema.

Every data-transforming schema change lands here as a ``NNNN_slug.py``
module and **stays here permanently**. The directory is the history, in
order; each database's ``applied_migrations`` ledger records how far
through it that database has got. The pending set is the difference, so
every install computes what it still owes from its own rows plus the code
it is running, and the boot converge applies it.

Nothing is deleted after an apply. A module that is gone cannot be applied
by a universe that never received it, which is precisely how installs
silently diverge. Entries are folded into the baseline schema only by an
occasional squash, once every known install's ledger is verifiably past
them.

Contract for a module here:

- ``apply(conn)`` is required, and **must not commit**. The applier commits
  the body and the ledger row together, which is what makes "applied but
  unrecorded" impossible; a commit inside ``apply()`` splits that
  transaction and gives the state back.
- ``invariants(conn)`` is optional. It runs after the apply commits, and
  again on every fleet preflight against a copy of a live database. So it
  may assert only what the entry permanently owes: the schema shape it
  produced, or a data fact no live writer can undo. A count of rows in the
  state the apply happened to leave behind is a snapshot, not an invariant —
  the writers that fill those rows afterwards are doing their job, and the
  assertion fails on every preflight from the first one onward.
- Invariants remain true forever unless a later entry declares
  ``RETIRES_INVARIANTS`` naming those prior entries — because the surface
  they describe is gone, or because the claim was never an invariant.
  Correcting one is always a new entry: an applied entry's bytes are
  recorded in every ledger that ran it, so editing the module in place makes
  those databases refuse to boot on a content mismatch.
- **The body must be safe to re-run.** A database restored from a
  pre-ledger archive replays its history, so guard every statement
  (``IF EXISTS`` / ``IF NOT EXISTS``, or an explicit state check).
- The filename stem is the entry's only identity — it is what the ledger
  stores. Do not add a name constant that could disagree with it.

Pure-additive net-new tables and columns do **not** belong here: those are
authored in the schema modules and self-propagate through the converge step
on the boot after a deploy.
"""
