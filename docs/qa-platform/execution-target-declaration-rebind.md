# Execution-target rebind after a declaration change

A QA requirement stores an immutable execution-target snapshot. Correcting
an environment's declared facts (`hosts.*`, `distribution.*`, `role.production`)
moves that snapshot's digest even when the case still names the same
environment row and the same subject. The snapshot-reuse, retract, and
supersession guards stay as they are: none of them may silently rebind a
row that holds a verdict.

`yoke qa requirement rebind-target` is the missing act. It points the row
at the live declaration of **the environment the case already exercised**,
keeps the recorded runs and verdict, and writes `rebound_from_target_json`
(the previous declaration), `rebound_from_digest`,
`rebind_endpoint_delta_json` (which facts moved, from what to what),
`rebound_at`, `rebind_rationale`, and `rebind_actor_id`. Two opaque hashes
are not enough: a later reader must be able to reconstruct the delta from
the row. The same command also accepts a snapshot that records **no
environment.id** and whose **endpoints already match** the resolved
environment, even when its site label is stale or incoherent. Endpoints are the
stronger evidence of what was actually exercised; a site label is
bookkeeping. A live item requirement cannot be superseded.

Identity is not an endpoint check. The same environment row can have
`hosts.app` corrected from `api.upyoke.com` to `https://api.upyoke.com`
(scheme/defaulting only) or repointed to another host. The first is a
rebind; the second is a different target. The command refuses when any
URL endpoint's resolved host authority (`host[:port]` after defaulting a
missing scheme to `https`) changes, reports that delta, and names a
fresh execution. A scheme-only or scalar declared-fact change is in.

Live identity is the environment the case actually ran against, not the
environment that shares the plan project's name. A plan's project and its
`target_environment_id` can belong to different projects — a yoke plan
targeting hosted `Yoke API`/`prod` is the normal shape. Rebind therefore
resolves, in order, a stored `environment.id`, the plan's
`target_environment_id`, then `site.name` plus `environment.name`. It
does not resolve `(project.id, environment.name)`: that name repeats
across projects and selects the plan's own `prod` instead of the hosted
row. An identity refusal names the resolved environment id, the field it
came from, and what the snapshot named, so a wrong row is not reported
as a genuinely different target.

```text
yoke qa requirement rebind-target --requirement-id N --rationale '...'
```

It is not a waiver and not a re-run. A different environment, a different
deployment receipt, a different subject, or a repointed host still needs
a fresh execution or sanctioned retirement/supersession.

## Do not strand the digest silently

`yoke projects environment-settings merge` knows which environment it is
writing. When a written path is an input to the execution-target digest and
requirements are bound to the digest that write will move, the merge
reports the bound count and item ids and refuses unless
`--acknowledge-stranded-evidence` is set. The write is cheap; discovering
the fallout one close-out refusal at a time is not.

## Snapshot reuse names this recovery when it applies

`require_existing_target` still refuses to reuse a row bound to a different
digest. When the mismatch is a declaration correction of the same
environment, or a snapshot whose endpoints already match the resolved
environment, **and** resolved host authority is unchanged, that refusal
names `yoke qa requirement rebind-target`. When the host authority
actually changed, it names a fresh execution. It does not name
`supersede` to a caller holding a live item requirement.
