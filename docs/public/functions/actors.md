# Actors and org roles

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Functions](index.md) > Actors and org roles
<!-- /yoke:breadcrumbs -->

Actors functions use global targets and the bound actor. Roster returns kinds, states, org/project
roles, linked email, live-key metadata, current actor and org management capability. State
changes require org owner or admin; disabling revokes keys and browser sessions.
Role set targets an actor id or linked member email and replaces their one org role,
returning old/new roles and changed state. Sign-in once resolves unlinked email; ambiguous email needs id. System-actor
retirement also requires `--confirm-system-retirement`; inspect the actor and credential owner
before explicitly confirming that retirement.

A person has exactly one role from `yoke_core.domain.actor_role.HUMAN_ORG_ROLES`: owner, admin, operator or
viewer. Operator works across the org's projects. Machine-only roles are deployment_ci,
hosted_service, infrastructure_ci, migration_verification_ci and preflight_executor; system roles accumulate. Every
grant uses the same person-role validator, including invites, sign-in, bootstrap and local seeding.
Invite-role validation precedes creation, linking or acceptance; refusal names revoke recovery.

```sh
yoke actors state set <actor-id> --disable
yoke actors role set <actor-id> --role ROLE
```

| Refusal | Recovery |
|---|---|
| owner_protected | Ask an owner to grant owner or change an owner. |
| last_owner | Make another active person owner before removing the last. |
| machine_only_role / role_not_assignable | Choose a supported person role. |
| actor_not_human | System roles come from their provisioning credential. |
| actor_not_found | Refresh roster. |
| member_not_linked | Member signs in, or use actor id. |
| member_ambiguous | Use exact actor id. |
| permission_denied | Caller must have org owner or admin authority. |
