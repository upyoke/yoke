# Blitz document handoff

Keep existing pinned workflow; new filing defaults Dash unless structure or
operator direction needs otherwise. For a document chunk needing Blitz:

1. File /yoke idea --workflow blitz, and link before claim:

```text
yoke strategy execution link ITEM --slug {SLUG} --project {_project}
```

Encode dependencies or explicit no-edges in that same batch action. Never
offer title-only claimable work.
2. Choose parent/another active doc for continued steering. Release the pair
   so the worker can claim its Blitz doc; this atomically releases the document lock:

```text
yoke claims steering release {CLAIM_ID} --reason blitz-handoff
yoke claims steering acquire --project {_project} --doc {NEXT_SLUG} --reason "steer {NEXT_SLUG}"
```

Retain new claim id and read inherited role digest. The gap strands no mail:
unowned role reports park. No successor doc means terminal steering handoff:
launch worker then stop, no live doc-less seat.
3. Launch via worker-lifecycle. Successful Blitz done automatically archives
linked execution doc and releases item-owned doc claim. No manual archive or
relock archived doc; continue only on active parent/successor through normal pair.
