# Event actor identity

Event rows identify a human or system principal through `actor_id`. The
engine does not store platform-user identity, so the event ledger has no
separate human-user column or query filter.

The governed `events_actor_identity` migration takes an exclusive table lock,
then removes the nullable legacy column and its index only when every stored
column value is empty and every historical envelope either omits the legacy
key or stores it as null. It preserves the event row count and leaves
historical JSON envelopes untouched. Fresh emitters omit that key entirely.

The migration fails closed when it sees non-empty column identity, non-null
envelope identity, malformed envelope JSON, a missing pre-cutover index, a
changed row count, or either retired schema object after apply. The
retired-schema registry prevents ambient schema convergence from re-adding
the column. Historical envelopes can contain escaped NUL characters inside
captured tool output. The preflight substitutes a harmless non-NUL code point
only in its temporary JSONB expression so PostgreSQL can inspect the top-level
identity key; the stored envelope text is never rewritten.
