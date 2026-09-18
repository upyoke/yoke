# Merge candidate review: what it guarantees, and what it does not

A merge candidate review holds one item's landing until a person has cleared
the exact commit the merge would carry. The clearance is an ordinary decision
request keyed `<item_id>:<full sha>`, so a new commit is a different subject
and inherits nothing, and the gate sits at `route_standalone_landing` — the
one boundary behind merge-when-ready arming, queue enqueue, and the direct
local merge a queue-less project uses.

This note exists for the part that is easy to get wrong when reading the
code: **what the gate is, and what it is not.**

## It is a mistake-stopper with an audit trail

The gate stops the ordinary failure it was built for: a worker finishing its
own item and landing it before the person who asked to read it has read it.
That failure is not adversarial. It is a green gate, a worker doing exactly
what it was told, and nobody in between.

## It is not a security boundary, and cannot be one here

Authority for an ordinary decision request is the ACTOR's role. That is not
enough for this kind, because on a single workstation every surface — the
steering seat, each worker, the UI — acts through the **same operator
credential**. The actor is identical for all of them. So the gate binds to
the SESSION instead:

- the session holding the item's work claim may never clear it;
- a session holding a live steering seat covering the item may;
- a session-less call may, but only under the origin mark this machine's UI
  server sets around its own dispatch.

The limit is structural, and worth stating plainly: **the server derives only
the actor from the credential — the session id travels in the envelope as the
caller wrote it** (`bind_actor_from_auth` says so in as many words). A caller
that types another session's id is asserting, not proving. No server-side
check can close that on a shared-credential machine, because there is nothing
left to check it against.

So the defence is layered rather than cryptographic:

1. **The hook denies it before the command runs.** Passing a foreign
   `--session-id` to `yoke decision-requests resolve`, or to a
   `yoke workflows item-posture amend` that relaxes
   `merge_candidate_review`, is refused by `lint-claim-ownership-mutations`
   (roster: `lint_session_bound_yoke_commands`).
2. **The session-less branch needs an origin nothing can type.**
   `ui_browser_origin` is process-local, set by the UI server around its own
   in-process dispatch. It never crosses a wire, so a relayed call and a
   session-less call on a machine API token both arrive without it.
3. **Every answer records the session that gave it.**
   `decision_request_decisions.decided_session_id` sits beside the actor,
   because on this machine the actor tells you nothing and the session is the
   whole audit.

What remains: a caller determined to evade this can. It has to suppress a
hook, or import `ui_browser_origin` and lie on purpose. That is the line this
design draws — **accidents and convenience are stopped; evasion becomes
deliberate and visible** — and it is the honest limit, not an oversight.

## The residual outside Yoke entirely

A raw `gh pr merge --auto`, a merge from the GitHub web UI, or a push
straight to the base branch reaches no Yoke hook at all, so no admission gate
on this boundary applies — the same residual the pre-merge QA proof and the
review-readiness stage check already carry. Closing that needs a
repository-side control (branch protection requiring a check that consults
the clearance), not more code at the merge boundary.
