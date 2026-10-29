# Act on every fleet finding

Answer every row the same turn: act, or write one line saying why the wait is
still sound. Live rows win over remembered plans. A row that should clear itself
(unmergeable queue entry, missing notice, refused worker command) is a
system gap: root-cause it in a subagent and report feedback before any
manual step. Send Yoke problems to Yoke and project findings to your universe:

```text
yoke feedback --to yoke --category failed --evidence 'Yoke finding: ...'
yoke feedback --to universe --category observation --evidence 'Project finding: ...'
```

- **Available / `unstaffed-ready`**: recheck the holder, then launch.
- **Deadlock / waiting chains**: staff a `!` blocker, or narrow or remove the
  heavier edge:

```text
yoke items dependency update DEPENDENT BLOCKING --match-gate-point GATE --gate-point coordination_only --rationale TEXT
```

- **Waiting to land / in flight**: do not staff; quiet is expected. Leave an
  unmergeable queue entry to its holder and observer; never message it.
- **Unattended linked work / mail awaiting a seat**: take the named seat.
- **Idle holder**: message it; `native_process_gone` means wake, not terminate.
- **Undelivered message**: wake only if no attempt is moving. An ended
  recipient: handle or re-address its work, then `yoke messages cancel MESSAGE-ID`.
- **Unregistered or abandoned launch**: read its failure, then reconcile or
  retry it ([worker-launch.md](worker-launch.md)); never a duplicate create.
- **Stranded or vendor-stopped**: never wake; restaff with headroom.
- **Landed without close-out**: holder reruns `yoke merge item PREFIX-N`; never
  merge twice.
- **Dead wait**: answer for the ended session.

```text
yoke session-control evidence get --session SESSION-ID
yoke session-control session wake --item PREFIX-N --prompt "Resume: the named blocker cleared" --json
```

Plan limits do not gate launch; unreadable is not exhausted. Capacity does.
