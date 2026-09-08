# A wake resumes its target in that session's own workspace

Decision recorded 2026-09-08.

## Decision

The working directory a relay hands a native for a **wake** comes from the
target session's own durable `harness_sessions.workspace`, not from the
project on the message that woke it. A **launch** keeps the project checkout,
because a launch has no session yet.

The wake job carries that directory as `RelayJob.target_workspace`, resolved
once on the server from the session row and handed to
`session_relay_runtime.execution_context`, which every surface adapter takes
its `checkout` from. Claude, Codex, and Cursor need no adapter branch: the
resolution is central, and the surface plays no part in it.

## Why

One session legitimately works across projects. The recipient row on a
session message carries the project the envelope was **addressed** under —
for an item-addressed message, the item's project — which is not always the
project the session runs in. Routing the resume by that project sent the
native looking for a conversation in a checkout it had never run in.

A native session is reachable only from the directory it started in. Claude
keys its stored transcript on that exact path; every surface inherits its cwd
from it. So the observed failure was total rather than degraded: a session
started in one checkout and messaged about another refused three deliveries
in a row as `transcript_missing`, while the original transcript sat exactly
where it had always been.

The session row already held the answer. Nothing new had to be recorded, and
no second identity registry was introduced — the durable workspace the
session registered with is the fact the resume needed all along.

## Authorization is a separate axis

Nothing here changes who may message whom, or which project a message is
addressed under. The recipient's `project_id` still travels on the job and
still governs relay project scoping; only the directory changed. Message
authorization, item routing, and project scoping are untouched.

## A missing workspace is named, not worked around

When the recorded workspace is not a directory on the machine — a lane
removed after its item merged, for instance — the relay refuses with
`session_workspace_missing` and reports the path it looked for. It does not
fall back to the project checkout: that fallback is precisely the defect
above, and it would resume the session somewhere its conversation has never
existed. The operator's next move is to look at the named path, or to
terminate the session deliberately if its lane is gone.

A job that carries no workspace at all still takes the project checkout, so a
relay newer than the control plane it polls keeps waking sessions during a
rollout window rather than refusing every one of them.
