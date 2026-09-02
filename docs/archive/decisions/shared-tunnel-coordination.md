# The local SSH forward is a shared machine resource

One loopback port carries every process on an operator machine that reaches a
connected environment's Postgres. Readiness treated that forward as if each
process owned it: probe, and if the probe fails, terminate every matching ssh
pid and start a fresh one. That is correct for one process and destructive for
two, and the fleet migration preflight — minutes of `pg_dump` through the same
forward — is exactly the operation that makes the second process's mistake
expensive.

Three failures on one afternoon, all the same forward on `127.0.0.1:6547`:

1. **Killed mid-copy.** A stage driver and a prod driver ran concurrently. The
   prod driver was six minutes into the largest tenant's dump; the stage
   driver's probe timed out under that load, decided the forward was dead,
   terminated it, and started its own. The dump died with `connection refused`
   and the prod release failed before dispatch.
2. **Lost the bind race.** The retry enumerated tunnel pids, terminated them,
   and by the time it started ssh the other driver had bound a new forward:
   `bind [127.0.0.1]:6547: Address already in use`. A working forward was
   sitting on the port and the run refused it.
3. **Killed by its own keepalives, alone.** With no other driver on the
   machine, the same dump died after ~6 minutes and a fresh forward appeared
   immediately after. `ServerAliveInterval=30` with `ServerAliveCountMax=3`
   gives ssh a 90-second window for a keepalive reply, and that reply queues
   behind bulk data like everything else.

## What the code does now

**A lifecycle lock** (`connected_env_tunnel_coordination`) serializes
probe-and-replace machine-wide, keyed by local port, under the machine Yoke
home. It is `flock`, so a killed driver releases it by exiting rather than
wedging the forward for the next one. The decision to replace is re-taken
inside the lock: a waiter usually finds the neighbour it queued behind has
already healed the forward.

**Adoption** (`connected_env_tunnel_lifecycle.replace_forward`): a matching
forward that answers a probe is the working forward, whoever started it. It is
adopted rather than terminated, and the port is re-examined after termination
so a neighbour that binds in that window is adopted too instead of failing the
run on its bind.

**A use lease** records that a process is mid-operation through the forward.
Rather than terminate a leased forward, `replace_forward` keeps re-probing it
for a bounded window — a forward under a bulk transfer is usually slow rather
than dead, so this is what lets two drivers share one machine — and only then
refuses, naming the holder, its reason, and how long it has held it. The fleet
preflight takes a lease for the whole rehearsal. A process ignores its own
lease, so it can still heal the forward it is itself using.

**Load tolerance** on both sides of the forward. The readiness probe's connect
timeout and confirmation window are sized for a saturated forward, not an idle
one; a forward that is genuinely gone still fails fast on the cheap port check.
ssh's keepalive window is widened for the same reason — the readiness probe is
the authority on liveness, so ssh's own window only has to be generous enough
not to pre-empt it.

**The copy reconnects.** A dropped forward is what most transient copy failures
are, so the rehearsal's dump treats every connect-class failure as retryable,
restores the forward, and copies that tenant again rather than failing the run.

## Why not simply serialize the drivers

Concurrency is a trigger, not the cause — failure 3 had no second driver. The
forward is shared by every Yoke process on the machine, including ones no
release train knows about, so the coordination has to live where the forward is
managed rather than in whatever happens to be driving it.

## Related

A deploy driver also died on a 60-second subprocess timeout while polling
GitHub through the relay, abandoning a run whose workflow was still alive. A
status read that hung says nothing about the workflow it was asking about, so
that read is now reported as a transport failure and retried inside the stage's
own budget (`deploy_pipeline_poll_authority.timed_out_result`).
