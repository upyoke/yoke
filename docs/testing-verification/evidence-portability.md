# Evidence portability

Evidence lives in the store of the build serving the universe, because that
build answers every reviewer's read. A capture run through a `*-db-admin`
connection relays its evidence writes (`qa.artifact.add`,
`qa.artifact.presign`) to the paired https connection — `prod-db-admin`
writes through `prod` — so a hosted Inbox or Shipping view shows the real
screenshots. A door with no paired https connection refuses with
`evidence_plane_unresolved` and names the `yoke connection set` repair, and
a local write through such a door refuses with `evidence_not_portable`. A
local universe keeps storing and rendering evidence on its own disk.

No human review request is created while an artifact it would show is
unreadable where the reviewer looks; the refusal names each artifact and the
recovery. Already-captured local-only evidence is repaired on the machine that
captured it, in place — same artifact row, run, verdict, and pending request,
with the replaced handle kept as provenance in the artifact's metadata:

```text
yoke qa artifact rehome --requirement-id <id> --artifact-id <id> [--artifact-id <id> ...]
```
