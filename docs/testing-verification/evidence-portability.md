# Evidence portability

Evidence lives in the store of the build serving the universe, because that
build answers every reviewer's read. A capture run through a `*-db-admin`
connection relays its evidence operations (`qa.artifact.add`,
`qa.artifact.presign`, `qa.artifact.rehome`, `qa.artifact.read` and
`qa.plan_review.begin`) to the paired HTTPS connection — `prod-db-admin`
reads and writes through `prod` — so a hosted Inbox or Shipping view shows the real
screenshots. A door with no paired https connection refuses with
`evidence_plane_unresolved` and names the `yoke connection set` repair, and
a local write through such a door refuses with `evidence_not_portable`. An
unreachable relay refuses instead of falling back to a local store. Other
routine operations, including metadata-only `qa.artifact.get`, refuse a door
with a paired https connection as `use_https_env`; only the direct-database
operations in `yoke_contracts.direct_database_access` stay on it. A
local universe keeps storing and reading evidence on its own disk; a
self-hosted universe uses its own declared serving connection.

No human review request is created while an artifact it would show is
unreadable where the reviewer looks; the refusal names each artifact and the
recovery. Already-captured local-only evidence is repaired on the machine that
captured it, in place — same artifact row, run, verdict, and pending request,
with the replaced handle kept as provenance in the artifact's metadata:

```text
yoke qa artifact rehome --requirement-id <id> --artifact-id <id> [--artifact-id <id> ...]
```
