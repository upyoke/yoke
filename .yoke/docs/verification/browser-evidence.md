# Browser Evidence

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Browser evidence
<!-- /yoke:breadcrumbs -->

How to read the evidence a [Browser case](browser-scenarios.md) captured, and
what its gate waits for.

## Reading a capture

Read captured evidence with the command the capture already reported under
`artifact_reads`:

```bash
yoke qa artifact read \
  --requirement-id <requirement-id> \
  --artifact-id <artifact-id>
```

It lands the bytes under this machine's temp root and reports that path as
`path`. The printed result omits the presigned download URL. Open that path,
not the capture's own `artifacts` scratch paths. Add `--output PATH` to choose
the destination yourself.

New full-page screenshots stop at 10,000 CSS pixels in height and record `clipped: true` in artifact metadata when truncated. Capture a smaller region or scroll and capture each screenful to show the rest. New evidence uploads, including S3 handle registrations, refuse files over 20 MiB; existing stored evidence remains exportable.

A full-page capture of a long screen can be a tall image, and a viewer
that scales it to fit makes every label in it unreadable. Read the part being
judged instead:

```bash
yoke qa artifact read \
  --requirement-id <requirement-id> \
  --artifact-id <artifact-id> \
  --region 0,900,1440,600 \
  --scale 1.5
```

`--region x,y,w,h` is a pixel rectangle measured from the top-left of the
capture; `--scale` multiplies the rendered size and applies after the region,
so one panel can be enlarged to read its small text. The stored artifact is
never modified — a view is a way of reading evidence — and the response
reports the `artifact_view` it rendered (source size, region, scale, rendered
size), so a finding can name the region it was seen in. A region falling
outside the image, an unreadable scale, and a non-image artifact each refuse
by name and say where the recorded bytes landed.

Artifact reads and `yoke qa plan review-begin` use the same evidence plane as
captures. Local-only universes keep reading local evidence, and remote
universes use their own serving connection. An unresolved evidence route
refuses with `evidence_plane_unresolved` and names the connection repair.
Configure the named connection or ask its operator to restore it, then retry.
An unavailable serving connection refuses; it never falls back to a different
store on this machine.

A read checks that stored evidence still exists before handing it out. When
the object a capture recorded has been deleted from the store, the read
reports `evidence_missing` with the address it looked for, rather than a link
that cannot open; re-run the case to capture it again.

Captures store their screenshots through the build serving the universe, so a
hosted reviewer sees the same images through the configured evidence plane. No review request is raised against a screenshot a hosted reviewer
cannot open. Evidence already recorded only on the capture machine is moved in
place from that machine with
`yoke qa artifact rehome --requirement-id <id> --artifact-id <id>`.

## What the gate waits for

The transition remains blocked until every blocking, materialized or explicit
requirement has passed or been waived. Capture success alone is not a visual
quality verdict: inspection checks both visible defects and consistency with
the expected outcome.

Browser passes must record an observed build at or carrying the revision
under verification. Before delivery, new lane commits require fresh evidence.
At member close-out, the selected completion run's delivered project commit
is the authority, including while the run settles its members. Synchronizing
the lane with the base branch after delivery does not stale that proof.
Re-run a stale case with `yoke qa case run --requirement-id <id>`.

## Related

- [Verification](index.md)
- [QA platform](platform.md)

Evidence uses its requirement's project: deployment member, then plan, then
item (including an epic task), then release run. A cross-project release case
therefore keeps its plan's project key. Reads reject a different stored key
as `evidence_key_mismatch`; re-run the case to re-capture its evidence.
`yoke qa artifact rehome` moves local bytes only and cannot repair an object
already stored under the wrong key.
