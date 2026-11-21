# Act on every fleet finding

Answer every row the same turn: act, or write one line saying why the wait is
still sound. Live rows win over remembered plans. Apply this rule to every alarm
and finding: If Yoke should have handled this automatically, root-cause it with
a subagent and file feedback first; a nudge is a workaround.

- **Available / `unstaffed-ready`**: recheck the holder, then launch.
- **Deadlock / waiting chains**: staff a `!` blocker, or narrow or remove the
  heavier edge:

```text
yoke items dependency update DEPENDENT BLOCKING --match-gate-point GATE --gate-point coordination_only --rationale TEXT
```

- **Waiting to land / in flight**: do not staff; quiet is expected. Leave an
  unmergeable queue entry to its holder and observer; never message it.
- **Unattended linked work / mail awaiting a seat**: take the named seat.
- **Idle holder**: inspect the evidence; after root-cause-and-file,
  wake a holder with `native_process_gone` or message a live quiet holder if that
  workaround is still needed.
- **Stale walk / `stale_walk=`**: the owner's QA walk is aborted at 30 silent
  minutes. Tell it to run its next step through `yoke qa mission host-command`
  or release the host; it has its own mail.
- **Undelivered message**: wake only if no attempt is moving. An ended
  recipient: handle or re-address its work, then `yoke messages cancel MESSAGE-ID`.
- **Unregistered or abandoned launch**: read its failure, then reconcile or
  retry it ([worker-launch.md](worker-launch.md)); never a duplicate create.
- **Stranded or vendor-stopped**: never wake; restaff with headroom.
- **Landed without close-out**: holder reruns `yoke merge item PREFIX-N`; never
  merge twice.
- **Dead wait**: answer for the ended session.

After root-cause-and-file, use the supported recovery and label it a workaround:

```text
yoke session-control evidence get --session SESSION-ID
yoke session-control session wake --item PREFIX-N --prompt "Resume: the named blocker cleared" --json
```

Plan limits do not gate launch; unreadable is not exhausted. Capacity does.
