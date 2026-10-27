# Team collaboration

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Team collaboration
<!-- /yoke:breadcrumbs -->

You can use Yoke solo, including from multiple machines, or share a Universe with a team in self-hosted or hosted mode. Everyone works against shared strategy, items, claims, and delivery records, so agents can coordinate across people, machines, and harness sessions.

## Share a Universe

Each person joins under their own identity and connects their own machines. Local mode is reachable on one computer only; use [Self-hosting](self-hosting.md) or hosted mode when teammates need to connect.

Shared access does not mean shared ownership of every task. A work claim identifies the session responsible for an item. Steering seats coordinate a project or a document's work, and fleet messaging carries questions, blockers, and results between sessions.

See [Steering and fleet control](sessions.md) for work coordination.

## Control access and decisions

### Actors and organizations

An actor is the identity that performs an action in a Universe. Human actors represent people; machine accounts represent services. Organization roles provide access across the organization, while project roles provide grants for a particular project.

Use the dashboard's **Team** page to see people, machine accounts, roles, and active API keys. Recorded identity makes work and decisions attributable without asking teammates to share an account.

### Invite and authorize people

An organization admin invites a teammate through **Team** or the `yoke invite` command. The server chooses the correct joining flow: a private code for self-hosting without company sign-in, company email sign-in when configured, or a Yoke account for hosted access.

Send a one-time invite code only to its intended recipient. Reissuing a code invalidates the old one; revoking an unused invitation prevents it from being redeemed. Once someone has joined, manage their access and machines rather than treating the original invitation as an ongoing credential.

See [Teammate invitations](../projects/teammate-invitations.md) for commands and recovery.

### Approve machines

A machine connection authorizes a computer to act as a particular person. Compare the displayed machine and code before approving it. Approve your own machines; a teammate should join through their own invitation.

A connected machine runs its relay and available harnesses under the configured identity. Model-provider sign-in remains a separate prerequisite for starting a coding agent. See [Machine authorization](../cli/machine-authorization.md).

### Roles and billing boundaries

Organization administrators manage access. Operators perform normal project work, and viewers have read access according to their role. Project grants can add project-specific authority. Machine-only roles serve particular automation functions and are not ordinary people roles.

Disabling an actor blocks access and revokes their API keys. Enabling that actor later does not restore the revoked keys; affected machines must reconnect. Yoke protects the last active organization administrator from being removed accidentally.

Hosted seats and billing are managed by the hosted platform. Local and self-hosted Universes do not have hosted seat billing. See [Team, roles, and billing](../projects/actors-members-billing.md) for the current permission and dashboard details.

### Human decisions

An agent can ask a question in a message or create a decision that a workflow, QA check, or deployment requires. These are different records. A message acknowledgement confirms receipt; an approval settles the specific decision shown on its card.

Use **Inbox** to see decisions waiting on you and the evidence attached to them. Read what the action approves and who may decide before answering. A release approval does not automatically settle every item's separate QA or work approval.

See [Yoke web dashboard](dashboard.md) and [Quality assurance](qa.md).
