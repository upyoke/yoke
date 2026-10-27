# Steer — worker lifecycle

## Dependencies

Record blockers as edges before launch:

```text
yoke items dependency list PREFIX-N --json
```

Shared files alone need `coordination_only`; use `fact:merged` when merge suffices.
Failed delivery QA: `.yoke/docs/verification/failed-item-qa.md` owns closure
milestones, retained-owner waits and supported manual resume.

## Quiet is not dead

Parked or release-wait quiet is not failure; the holder keeps its
claim through delivery QA. A merged item that owes nothing has no holder;
its release closes it. Message a quiet worker first. Terminate only an
unresponsive worker, a restaff or cleanup. One fresh session per item.

## Survey a neighbour before an ordered edit

```text
yoke claims work holder-get --path SHARED_PATH
git -C ABSOLUTE_REGISTERED_NEIGHBOUR diff -- SHARED_PATH
```

Read only; then follow `lanes-and-claims.md`.

## Restaff on a different model

```text
yoke items section get PREFIX-N --section 'Progress Log'
yoke sessions terminate {WORKER_SESSION_ID} --reason "restaff PREFIX-N at {_level}: reason"
yoke qa plan adopt --item PREFIX-N --execution-id ID --reason TEXT
```

Ask for a checkpoint first. Launch the successor with key
`steer:{_project}:PREFIX-N:restaff:{PREVIOUS_LAUNCH_ID}:{_level}`. It adopts
any predecessor QA execution.
