# Blitz document handoff

For a doc chunk that needs Blitz, file it with `/yoke idea --workflow blitz`,
then:

```text
yoke strategy execution link ITEM --slug {SLUG} --project {_project}
yoke claims steering release {CLAIM_ID} --reason blitz-handoff
yoke claims steering acquire --project {_project} --doc {NEXT_SLUG} --reason "steer {NEXT_SLUG}"
```

Launch the worker. With no successor doc, stop after launch.
