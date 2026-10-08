# Actors function family

The Actors page and its CLI adapters. Every function takes a `global` target
and binds the calling actor. Envelope and dispatch rules are in
[functions.md](functions.md).

| Function id | CLI adapter | Owner module | Contract |
|---|---|---|---|
| `actors.roster` (read) | none; browser-proxied | `yoke_core.domain.handlers.actors_roster` | Every actor with its kind, state, org and project roles, linked sign-in email, and live API keys, plus `current_actor_id`, `can_manage_actors` (the caller is an org admin), and `person_org_roles` — the org roles a person may hold. |
| `actors.state.set` | `yoke actors state set ACTOR-ID (--enable \| --disable) [--confirm-system-retirement]` | `yoke_core.domain.handlers.actor_state` | Org admin. Enables or disables an actor; disabling revokes its API keys and browser sessions. |
| `actors.role.set` | `yoke actors role set (ACTOR-ID \| --member EMAIL) --role ROLE` | `yoke_core.domain.handlers.actor_role` | Org admin. Sets a person's one org role. Payload `{actor_id \| member_email, role}`; `member_email` resolves the actor linked to that sign-in email in this universe. The new role replaces the old one. Result `{actor_id, role, previous_roles, changed}`; a person still holding several roles from before the one-role rule converges onto the one set. |

## A person's one org role

A person holds exactly one org role from
`yoke_core.domain.actor_role.HUMAN_ORG_ROLES`: `admin`, `operator`, or
`viewer`. `operator` at org scope is normal Yoke work across every project in
the org. `deployment_ci`, `hosted_service`, `infrastructure_ci`, and
`migration_verification_ci` are `MACHINE_ONLY_ROLES`; a system actor's org
roles accumulate.

Every org grant goes through `yoke_core.domain.actor_permissions.grant_actor_org_role`.
For a person it applies the same rule as `actors.role.set`, through
`actor_role.check_person_role_change` and `actor_role.replace_person_role`:
invites, sign-in admission, bootstrap, local seeding, and
`actor_grants_cli grant-org` all refuse the same way. Sign-in checks an
invite's role before it creates, links, or accepts anything and refuses with
`invite_role_refused`, naming `yoke identity invite revoke INVITE_ID` as the
recovery.

## Refusal codes

| Code | Meaning and recovery |
|---|---|
| `last_admin` | The change would demote the org's last active admin. Make another active person admin first. |
| `machine_only_role` | The role belongs to machine credentials. Choose `admin`, `operator`, or `viewer`. |
| `role_not_assignable` | The role is not a person's org role. Choose `admin`, `operator`, or `viewer`. |
| `actor_not_human` | The actor is a system actor; its roles come from the credential that provisioned it. |
| `actor_not_found` | No such actor; refresh the roster. |
| `member_not_linked` | No actor is linked to the email. The member signs in once, or pass the ACTOR-ID. |
| `member_ambiguous` | The email is linked to several actors. Pass the ACTOR-ID. |
| `permission_denied` | The caller is not an org admin. |

The serving floor for `actors.role.set` is the next release; an older server
refuses it as `function_version_skew`.
