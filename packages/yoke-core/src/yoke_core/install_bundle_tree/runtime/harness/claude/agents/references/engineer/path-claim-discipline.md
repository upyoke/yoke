## Path-Claim Discipline

Read before editing or creating a path your claim does not cover. A required
file stays in scope; coverage is authority, not scope.

1. Read the dispatch's declared paths and the live claims:
   `yoke claims path list --item PREFIX-N --state active`.
2. Widen **before** the write, using that claim id and bundling paths that share
   a reason (`--allow-planned` for files not committed yet):

```text
yoke claims path widen --claim-id N --add-paths PATH1,PATH2,... --reason "<why>" --item PREFIX-N
```

3. A refused widen is an overlap with other work. Report it to the parent and
   stop; the parent records the coordination decision. Never request an
   override yourself.

Claims released at landing cannot be widened. Before editing a reopened lane,
register fresh coverage with `yoke claims path register --item PREFIX-N --paths
... --allow-planned` (add `--task-num N` for the landed epic task the rework
changes) and have the lane prepared again.
