# Decisions and approvals

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Decisions and approvals
<!-- /yoke:breadcrumbs -->

Your agent does most of the work on its own. When it needs a person, it files a decision request: a question it wants you to answer, or an approval a requirement needs before work moves on. Each request is recorded, so the answer, who gave it and when stay on file.

## Two kinds of decision

### Questions

A question is your agent asking for your call. It has a short question, the context you need to decide, and usually a few options. Each option says what happens if you pick it, and your agent marks the one it recommends.

A question gates nothing. Your agent keeps working on whatever it can while it waits for your answer.

### Approvals

An approval is a requirement that needs a person before work moves on. A workflow can require one before an item changes stage. A QA plan can require someone to review evidence the automatic review could not settle. A deployment flow can require sign-off before a release goes out.

Each approval settles only its own requirement. Approving an item's work does not approve its QA evidence or its release. See [Workflows and work items](work.md) and [Deployments and releases](delivery.md).

## How to answer

Answer in your agent conversation or in **Inbox** in the web dashboard. Both record the same decision, so answering in one answers both.

- In the conversation, your agent presents pending questions one at a time, with its recommendation, and records your answer.
- In **Inbox**, each card shows the question or approval, who asked and when, the context and evidence, and the choices. A question also has an answer box.

You can write your own answer instead of picking an option, unless the question requires a listed option. A question with no options always takes a written answer.

A question stays open until someone answers it or the agent withdraws it. A session that is idle between turns does not close its questions. When facts change, the agent can withdraw a question or replace it with a new one.

The answer goes back to the agent that asked. If that session has ended, it goes to whoever now holds the item.

## Who answers

By default, a question goes to the project's owners and operators. An agent can instead ask named people, or a named audience such as a team. Only the people asked can answer.

An approval names who may decide, by role or by person, and whether any one of them is enough or all of them must answer:

- **Any**: the first approval settles it.
- **All**: every listed approver must answer.

Under either rule, a rejection from any listed approver settles the request against. Each person decides once; a recorded decision cannot be changed.

## Learn more

- [Decision requests](../sessions/decision-requests.md): the commands agents use to ask, answer and withdraw.
- [Inbox and messaging](../sessions/inbox.md): how Inbox shows decisions and messages.
- [Steering and fleet control](sessions.md): how steering brings decisions to you.
