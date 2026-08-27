# Prove the session terminate path; keep ended-plus-killed

The public terminate surface is reachable and distinct from an ordinary
end. Keep it. Do not add a `terminated` liveness value, and do not retire
the kill mechanics.

## Why prove, not retire

`session_control.session.terminate` / `yoke sessions terminate` is the
operator and steering kill for an unresponsive worker. It is not the
same as `end_session(release_claims=True)`:

- it stamps `terminated_at`, `terminated_by_*`, and `termination_reason`
- it cancels undelivered messages and queues a native-process reap
- it permanently refuses wake and re-registration
- an ordinary ended session can reactivate; a killed session cannot

Workers self-END on a completed mandate. That does not make the kill
redundant. The kill exists for the session that will not end itself.

## Why the roster never accepted `terminated`

Liveness is `active | stale | ended`. How an ended session got there is
`ended_cause`: `killed` when `terminated_at` is set, `wound_down` for an
ordinary end. The roster State filter rejecting `terminated` is that
contract, not a broken enum. Every refusal still reads `terminated_at`
directly, so folding the presentation into `ended` changes no mechanic.

## Why production never showed a kill

The registered handler returned a success payload from the open
transaction and then closed the connection without committing. On
Postgres that rolls the kill back, so the caller saw `terminated_at`
once and the durable row never changed. The handler now commits on
success and rolls back on failure. A public-surface test asserts the
committed row, released claim, and `ended` / `killed` classification
survive a later rollback on the same connection.
