# A defunct process is an exited process

Decision recorded 2026-09-09.

## Decision

`yoke_contracts.process_ancestry.process_start_time` reads the process state
alongside the start time and answers `None` for a process in state `Z`. Every
caller compares its result against a start time it recorded, so a defunct
process now answers exactly as an absent one: gone.

## Why

The probe existed to defeat pid reuse — a recorded pid that is now a
different process must not read as the process that was recorded. It read
`ps -o lstart=` and compared the string. A zombie defeats that comparison
completely: the kernel keeps the entry, with the original pid and the
original start time, until the parent reaps it. Both halves match, so the
probe answered "still the process I wrote down" about a corpse.

Everything downstream inherited the wrong answer:

- the wake path asks this question before starting a native, so a session
  could not be resumed while its previous native sat unreaped — the wake
  deferred to a live turn that had already exited, and stayed pending;
- the machine's dead-session report asks the same question in reverse, so a
  session was reported alive and never settled;
- an anchor whose harness process had exited but not been reaped still
  resolved ambient identity to it.

One observed session showed the whole shape at once: a native that exited
cleanly, a `ps` state of `Z`, two wake attempts five minutes apart both
answering `native_turn_running` against that pid, and a stranded envelope.

## Cost

One `ps` call, unchanged — the state is another column on the invocation that
was already being made, and it leads because `lstart` is the only column in
that call whose value contains spaces.

## What this does not change

The start-time comparison stays exactly as it was for every running process,
and the returned string is byte-identical to what the previous form returned.
A caller that needs to know a process ran and has now exited reads the
launch's own diagnostic capture — its exit code and exit time — rather than
inferring it from the absence of a probe answer.
