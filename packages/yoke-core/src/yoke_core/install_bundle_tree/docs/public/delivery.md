# Delivery

Workbench delivery has three destinations, and **Deployments** carries two
tabs because a flow definition and a run of it are two readings of one
subject:

| Destination | Meaning |
|---|---|
| **Deployments → Flows** | Pipeline definitions runs execute. Read-only: create, version and disable them with `yoke deployment-flows create`, `version` and `set-status`. |
| **Deployments → Runs** | Each execution of a flow against an environment. The run ID opens that run. |
| **Environments** | Deploy targets |
| **Databases** | Declared DB models, posture, apply records — see [databases-and-migrations.md](databases-and-migrations.md) |

Flows is the tab Deployments opens on. Runs live at `/deployments/runs`, and
one run at `/deployments/runs/<run id>`.

Commits made outside Yoke ship without an item or attestation. Run pages,
Shipping cards, Runs tables and release approvals show **Also includes N
commits made outside Yoke**. Expand it to see each project's short commit SHA,
subject and author. Optional `yoke merge-receipt commits attest` ties a commit
to its owning item; installer refresh commits follow the same rule as any hotfix
or bot commit.

**Flows** lists every definition you can read, grouped by project with the
projects in the current scope first, and searches names,
IDs, stages and environments. Disabled definitions stay hidden until **Show
disabled (N)** is checked; only a flow that is not active carries a status
pill. The selected flow shows its name and ID, its description, and one facts
row — project, environment, target tier, on failure, and the flow it
replaces (`supersedes_flow_id`, linked). Its pipeline is a numbered list in
stage order, each stage naming what runs it ("GitHub Actions ·
release.yml", "Warm-up · prod", "Automatic", "Approval"); QA and approval
stages add their scope, where they run, and who decides, and stages a person
must decide are marked. Up to five recent runs of the flow link to their run
pages. On a narrow pane the list comes first and a chosen flow opens alone
with **‹ All flows** to return. The page has no controls that change a
definition: flows are created, versioned and disabled only through
`yoke deployment-flows create | version | set-status`.

Selecting a flow updates its shareable URL, survives reload, and supports
Back. **All flows** returns focus to the list. Action dialogs keep keyboard
focus inside, return it on dismissal, and prevent duplicate pending actions.

Packs distinguish a newer available version from an expired repository
report. Opening an update preview names the selected Pack and project and
moves focus to that preview. Environments and Databases keep unavailable
facts explicit and put detailed technical limitations behind disclosure.

**Runs** titles each row with its flow name and puts the run ID beneath it as
the link to the run. The QA evidence column holds a few small thumbnails with
"and N more" beneath; the run page has the rest. The table stacks each row
into labelled lines whenever its content pane cannot hold every column.
The run page reads that exact run across every project the viewer can access,
so its members include work from another project even when opened from a
project-filtered list. The list itself keeps its chosen project filter; run
checks and the target environment still belong to the run's owning project.

## Item-bound delivery

Frontier item cards show the newest run that named the item in each
environment, including recorded removals. A removed member reads
"removed · QA cancelled · rides a later release", or links the newer run
holding it. The removal reason is available on the outcome's tooltip;
removal changes QA custody, and does not remove the code from the build.
A failed or cancelled deployment keeps that outcome even when its member
QA cannot be read, with the QA reason available on the same tooltip.

`/yoke usher` and `yoke deployment-runs start-for-item` bind implemented work
to a run, execute the pipeline, and move members toward done. Flow id ≠ run
id (`run-YYYYMMDD-NNN`).

Membership is not by itself completion. A member closes only on a succeeded
run with completion authority for it: a run of the item's own selected flow,
or another project's run that recorded a bound source commit for the item's
project. Carried code, a failed run, or a same-project run of another flow
does not close it. So a final-delivery release refuses, before it executes,
a same-project member whose selected flow it cannot close. The refusal names
both repairs: select the run's flow for the item, or cancel the run and
deliver the item on its own flow. When a release with that authority
succeeds, it stamps each member's delivery evidence and closes every member
whose item and shared gates have passed, with no holder re-running a merge.
The run reads `succeeded` only after those close-outs have happened. Until
then it stays `executing` and settling (`settling_at`), a durable state that
counts as delivered for its members' own gates. Settlement then runs in two
phases. First, each cleared member's prerequisites are committed — its
delivery evidence stamped and its status preflight run — which closes
nothing and is safe to repeat. Then every member's terminal status and claim
release is written in one transaction and committed once, so members close
together or not at all, even if the process stops part way. One member's
refusal rolls the whole set back: no member closes, and every claim and lane
is kept. The refusal names each member — the
blocked ones with their own reason, the rest as held with the run so nobody
repairs a member that has nothing wrong. A final member the run could not
even try to close, such as one whose post-deploy obligations are unanswered,
holds the run the same way. A carried cross-project member whose own
completion flow declares no item QA and which has no explicit plan or
post-deploy requirement owes no answer: stage and fleet reports name its
own flow as the reason, and it closes with the release. Same-project members
and carried members whose own flow declares item QA still need an answer;
explicit obligations always run. Second, after that commit, the closed members'
effects run: GitHub sync, lane cleanup, and ending the holders' now-empty
sessions. They are idempotent, and a failure among them never reopens a
closed member. It keeps the run settling, naming the member and the failure,
until a replay finishes the effects and marks the run `succeeded`.
Settlement replays by itself when the blocking record is cleared or a
member's merge close-out commits `done`. The last recovered member therefore
finishes its settling run without a hand re-drive; remaining gates still
hold the run open. If the run stays `executing`, `yoke
deployment-runs update RUN status succeeded` replays it.

Residue is cleared on the way through. A member's own release walk opens an
item-level QA execution, and when the run scopes that member its own item
QA, the run-bound execution is the one that produces evidence while the
older row stays live under a parked holder. An item-level execution whose
cursor never advanced and that owns no result row has produced nothing, so
settlement aborts it with `superseded-by-run-scoped-item-qa` and closes the
member. One that did record a result keeps refusing, and its own walker
still owns it.
When a no-change Dash that never opened a lane is left at its release wait,
its holder closes it with `yoke lifecycle transition PREFIX-N --to done`.
That transition still requires the succeeded run, QA, and approval.

Whether final members close one at a time or together depends on the
selected flow. When it has no run QA and no run approval, each final member
closes on its own once its delivery lands and its own item QA is accepted or
discharged with no post-deploy obligation, even while a sibling is still
waiting. When the flow has either shared gate, every final member keeps its
claim, lane, and session until all item gates and shared gates pass, and the
run and its members then close together.

## Hosting

There is no separate Hosting destination. Hosting shows up as:

- Packs (production-deploy, runners, environment infra, …)
- `/yoke onboard` gated first deploy
- Environment settings (projected scalar reads only — never dump whole
  settings documents)

## Disable vs delete

Disable a flow definition to stop new assignments while retaining history.
Definitions referenced by runs are immutable.

## Item Delivery card

The item page names the run selected by the same completion-authority read
as the done gate: **Delivered by** when delivery succeeded, **Delivering**
while it is in flight, and **Also in** for other carrying runs. A release
from another project can deliver the item when its recorded bound source
has completion authority; matching flow names alone do not prove delivery.
Each run shows its flow → target environment. Terminal runs show **finished**
(succeeded) or **ended** (failed/cancelled) from `completed_at`; executing
runs show their current stage and **started** from `started_at` (or
`created_at` before execution starts). A missing terminal timestamp is
reported as unavailable rather than substituted with the creation time.
The **Item’s flow** row is omitted when that flow delivered the item. When
another flow delivered it, the selected flow says **not used: delivered by
the run above**.
