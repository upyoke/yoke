# Browser Evidence

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

A full-page capture of a long screen is one very tall image, and a viewer
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
