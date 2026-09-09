# An actor's name is not an identity

## What changed

`actors` carries one `name` column. The `actor_labels` table, which stored
that name once per surface (`display` for operator views, `github_label`
for issue attribution), is gone, and so are the helpers that read, wrote,
or resolved a label. A machine records which actor it operates a universe
as, by id, in its own config; sessions read that id back instead of
matching an OS login or a name.

## Why the surface split was wrong

The two surfaces held the same string for nearly every actor that had
both, so the split bought no expressiveness. It cost something concrete
instead: `github_label` was unique, which made it usable as a lookup key,
and code that needed "which actor is this?" answered it by matching a
name. Three consequences followed, and all three were live:

- **A rename moved an identity.** Anything that resolved by label would
  stop finding the actor, or start finding a different one.
- **Two people could not share a name.** The uniqueness constraint
  refused the second Ada Lovelace rather than preventing an ambiguity —
  a partial fix scoped uniqueness to the resolution surfaces, which
  narrowed the problem without removing the class.
- **A session's identity depended on the machine's OS login.** Session
  registration picked among several human actors by matching the calling
  process's login against a label. Two people at one machine, a login
  that differs from the name an account system supplies, or a renamed
  actor each produced either a refusal or — worse — the wrong person.

## The rule now

**Identity is `actors.id`. A name is what we call somebody.** Every
durable reference — sessions, work and path claims, org and project
roles, external identities, API tokens, machine ownership — keys on the
id and is untouched by a rename. `actors.name` carries no uniqueness of
any kind, because nothing resolves an identity from it.

`actors.resolve_actors_by_name` exists and returns a **list**. That shape
is the point: it is an operator search ("who is called this?"), and its
callers must handle the empty and multiple cases explicitly. It must
never choose a session identity, an authenticated caller, or an owner.
The two surfaces that still accept a typed name — addressing a message
recipient and an admin actor ref — refuse with every matching id named
rather than picking one.

## The local binding

A machine records `connections.<env>.operating_actor` in its own config:
the actor id, plus the universe that id belongs to. Both halves are
needed. The id alone would be filed under an env label, and an env label
is a machine-local nickname an operator can re-point at a different
control plane between two commands — at which point the recorded id
silently names a stranger. Recording the universe's own identity beside
it turns that retarget into a refusal somebody can read.

The universe's identity needs no new column: `seed_default_org` already
refuses a universe with anything other than exactly one organization
identity card, so that row's slug and creation instant identify it.

Writing the binding belongs to the paths that already know the answer —
universe birth, universe import, `yoke config bind-actor`, and the
doctor repair, which records it for a single-owner universe that predates
the binding. Reading it is by id only. Deliberately, **resolution has no
fallback**: a missing or stale binding refuses and names the command that
fixes it. A standing "well, there's only one human" fallback would
re-answer the identity question every time the recorded answer stopped
matching, which is exactly the moment somebody needs to be told.

## Attribution keeps its spaces

A person's name is "Ada Lovelace", not "Ada-Lovelace", so the render
adapter preserves interior spaces and collapses only what would break a
line (control characters and newlines). GitHub attribution labels render
the name verbatim with one exception: a leading `@` is stripped, because
GitHub reads it as a mention of whoever holds that handle, and an actor
name is chosen by a person or their account system and never vetted
against GitHub's user namespace.

## Landing

`0041_actor_name_replaces_actor_labels` adds the column, backfills it
(display name, then GitHub label, then system component — the order the
replaced readers used), and drops the table. It declares a serving floor:
a build older than the entry renders every actor by reading `actor_labels`,
so it cannot serve a converged database. The hosted companion adopts the
account name through `actors.set_actor_name` on the same contract.
