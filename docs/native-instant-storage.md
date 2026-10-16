# Native instant storage

SQL writers and comparison cutoffs bind aware UTC datetimes through
`db_helpers.instant_parameter`. PostgreSQL stores native timestamps;
SQLite test boundaries receive canonical RFC3339 text. Ingress parses wire
values before binding; strings, epochs and naive datetimes are not writer inputs.

Establish relevance before decoding historical evidence. Composition filters
landing candidates by qualified commit-clock windows before attribution;
exact commit evidence remains independent. A replacement pull request clears
its predecessor's timestamps, while retaining the same pull request preserves
its timestamps. Finished-item windows retain inclusive microsecond cutoffs.

Optional clocks use NULL for absence. Close-out can use qualified commit time
when no queue landing clock exists. Required clocks and nonempty evidence
retain strict decoding. Driver attachment JSON uses canonical RFC3339 values;
run identity/status projections do not need to parse unrelated clocks.

The permanent ordered migration `0070_native_domain_instants` owns historical
storage conversion. Keep it and its migration tests. Fleet rehearsal converges
each restored copy through `migration_fleet_preflight.rehearse` and exercises
product readers on the result; reader refusals fail the gate. The
[fleet contract](public/reference/db-reference/migration-model-fleet.md) owns
copy custody. The instant census is read-only diagnostic evidence and does not
earn a release receipt.
