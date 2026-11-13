# Decision requests

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Sessions](index.md) > Decision requests
<!-- /yoke:breadcrumbs -->

Ask, answer and withdraw decision requests. A decision request is either an
approval a requirement needs, or an operator question: a request that gates
nothing and asks a person for a call. [Decisions and approvals](../guide/decisions.md)
explains both for the people who answer them.

## Commands

| Command | What it does |
|---|---|
| `yoke decision-requests ask` | File an operator question; its answer arrives as Fleet mail. |
| `yoke decision-requests resolve <request id> <action>` | Record your decision with an action the request offers. |
| `yoke decision-requests withdraw <request id> --reason TEXT` | Cancel a pending operator question as its requesting session or steering. |
| `yoke decision-requests list --mine` | Read the calling session's questions and answers; `--requesting-session ID` reads another session's. |
| `yoke decision-requests get <request id>` | Show one request and its decisions to its originator or an authorized reviewer. |
| `yoke decision-requests dispose-ended` | Withdraw pending requests whose subject has ended, and return a receipt. |

`list` takes `--status pending`, `resolved` or `withdrawn`. Each command's
`--help` lists every option.

## Ask a question

```text
yoke decision-requests ask --key choose-color --question "Which color should the banner use?" \
  --option blue=Blue::"The banner matches the current site header." \
  --option green=Green::"The banner stands out from the header." \
  --recommend blue --item PREFIX-N
```

Use plain language, give the context needed to decide, name things in words
(any id follows the name in parentheses), and keep the question very short.
Write each option's detail as what happens if the person picks it.

| Option | Meaning |
|---|---|
| `--key KEY` | Stable lowercase key. Reusing a key while its question is pending returns the existing question. |
| `--question TEXT` | The question, at most 2000 characters. |
| `--context-file PATH` | Markdown context, at most 8000 characters. |
| `--option ID=LABEL[::DETAIL]` | Repeat for up to eight choices; label at most 80 characters, detail at most 500. |
| `--recommend ID` | The recommended option. |
| `--no-freeform` | Require a listed option. Needs at least one `--option`; with no options a written answer is required. |
| `--item PREFIX-N` | The item being discussed; the requester need not hold it. |
| `--replaces ID` | Withdraw this pending question and file the new one atomically. |
| `--attach PATH` | Attach an image or PDF; repeat per file. Maximum 20 MiB per file and 64 MiB for the encoded attachment manifest. |
| `--to PERSON` | Ask an actor id or unique human name in your organization; repeat per person. |
| `--audience NAME` | Ask a named audience. |
| `--project PROJECT` | The project the question is about. |

Attachments use the QA evidence store and viewer; `get` and `list` show their
names and count.

A worker with a live steering seat asks through `yoke say --steering`,
including the question, context, options and recommendation. Steering answers
from standing direction or files the question with `--session
REQUESTING-SESSION-ID`. Without a live steering seat, the worker files it
directly and omits `--session`. Do not wait on a harness prompt tool: continue
other in-scope work or end the turn.

## Who can answer

Without `--to` or `--audience`, the project's owners and operators answer.
`--to` and `--audience` replace that default, and only the people they name
can answer. Named audiences use live membership, including people added after
filing. Do not combine `--to` and `--audience`.

`--project` selects a visible project. Without it, `--item` selects its
project; otherwise an unaddressed question uses the session's project.
Explicit recipients or a named audience without a project or item create a
project-less question in the one organization shared by the asker and all
recipients, or in the named audience's organization. Several possible
organizations refuse; choose a named organization audience. A question with
neither project nor audience refuses `operator_question_audience_required`;
supply `--to` or `--audience`. A named audience must belong to the question's
project, or to its organization when project-less. See
[Audiences and shared posts](audiences-and-posts.md).

An approval's policy names its deciders by role or person. Under mode `any`
the first approval settles it; under mode `all` every listed role or person
needs its own decision. A rejection by any listed party resolves the request
against. Read `approval_progress` in the `resolve` reply for what the request
is still waiting on.

## Answer

The Inbox shows a question as its heading, then who asked and when, followed
by attachments, context as text, and choices. Asked by names the person and
what the asking session holds. The recommended tag sits above its primary
button; option details line up beneath the buttons. A labelled answer box
supports Send or Cmd/Ctrl+Enter. Answered cards appear in **Decided**.

Steering raises every pending Inbox decision in chat one at a time, with
context and its recommendation, reconciles the steering report against chat
whenever it reports, and records a chat answer with `resolve` immediately:

```text
yoke decision-requests resolve 17 blue
yoke decision-requests resolve 17 freeform --note "Use violet"
```

The server checks live authority and validates the action against the request
kind. Each person decides once: the same actor cannot decide the same request
twice. The same durable decision records the person and answering session
whether the answer came from chat or the Inbox. If steering lacks authority,
answer on the Inbox page.

## After the answer

The answer reaches the requesting session as Fleet mail on every supported
harness and machine, even while that session is idle between turns. If the
requesting session is terminated or removed, it goes to the item's current
holder. A failed delivery records `operator_question_undelivered` on the
request and in the steering report; read the saved answer and relay it to the
holder. The steering report names each departure once; see
[Steering report](steering-report.md).

## Withdraw or replace

Filed questions cannot be edited. The requesting session or steering may
cancel a pending question, or replace it atomically:

```text
yoke decision-requests withdraw 17 --reason "Direction changed"
yoke decision-requests ask --replaces 17 --key choose-color --question "Which shade?"
```

Replacement requires a pending operator question from the same requesting
session; the old request's withdrawal reason names its replacement. Withdrawn
questions leave both waiting lists and remain in session history.

A question stays open while its requesting session is idle between turns,
until someone answers or withdraws it. `dispose-ended` withdraws pending
requests whose subject verifiably ended, such as a question whose item reached
a terminal stage, or one whose requesting session has no item and was
terminated or removed. It first abandons QA plan executions that stopped
reporting progress. Reading the Inbox runs the same convergence.

## Related

- [Decisions and approvals](../guide/decisions.md)
- [Inbox and messaging](inbox.md)
- [Audiences and shared posts](audiences-and-posts.md)
- [Steering report](steering-report.md)
