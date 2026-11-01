# Blitz document handoff

When the operator chooses Blitz, file `/yoke idea --workflow blitz` with
dependency edges or explicit no-edges, then:

```text
yoke strategy execution link ITEM --slug {SLUG} --project {_project}
yoke claims steering release {CLAIM_ID} --reason blitz-handoff
yoke claims steering acquire --project {_project} --doc {NEXT_SLUG} --reason "steer {NEXT_SLUG}"
```

Launch the worker. With no successor doc, stop after launch. Never archive or
relock the Blitz doc by hand.
