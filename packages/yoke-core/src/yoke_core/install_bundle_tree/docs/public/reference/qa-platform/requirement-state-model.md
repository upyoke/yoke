# QA requirement state

QA authorization is a derived answer over existing requirements, executions,
review audit, definitions and proof. It has no separate persisted state machine.
`qa_latest_execution` owns actual-attempt selection; `qa_obligation_settlement`
owns discharged and replaced requirement predicates.

## Evaluation order

1. Determine the gate's owner, transition or phase, deployment subject and
   environment. Unrelated history does not enter its required set.
2. Honor explicit waiver or retraction. Follow a valid replacement to its final
   effective requirement. Declaration immediately removes predecessor grading,
   even while the successor is pending or failing. Validate same-scope edges,
   environment and execution target, missing successors and cycles in the
   declaring transaction. An empty target digest does not erase environment.
3. Select the newest actual execution by its aware `started_at` instant. Use
   execution id only to break equal starts. Select before considering verdict,
   completion, review, definition currency or proof. Pending and failing attempts
   outrank older passing attempts. Missing or ambiguous start evidence refuses
   as `qa_execution_order_ambiguous`; inspect the named owner and evidence with
   the control-plane operator before correction. Never substitute creation time,
   completion time, review time or id for missing start evidence.
4. Grade that execution's verdict, completion, required judgment and its own
   proof against the appropriate behavioral definition and target.
5. Require all applicable effective requirements to pass, then honor independent
   delivery, acceptance and live ownership prerequisites.

Attempt insertion, judgment and replacement validation serialize within the obligation scope so a concurrent write cannot change the selected attempt underneath automatic discharge or close a correction cycle.

An older unfinished attempt is history after a newer actual attempt. A live
plan execution, process or lease remains separately owned and must finish or
abort before terminal settlement. Selecting an attempt does not release it.

## Reviews

A review judges the actual captured run. It does not create an execution.
Plan review audit retains capture id, verdict and rationale; the bundle retains
reviewer actor and session. Responses, artifacts, completion notices and human
decision requests refer to that actual run. Replay of the same review no-ops;
a conflicting final judgment requires a real new attempt.

Historical separate review rows remain audit history. Durable review
associations classify them as judgment-only; a runner label does not. A real
agent execution remains an execution, and a self-referencing review association
keeps its actual capture eligible.

Human escalation resolves the exact run in its decision request. A resolved,
authorized decision may settle that run's provisional `undetermined` verdict to
`pass` or `fail`. The trigger verifies requirement, captured run, action, actor,
resolution time and rationale, and preserves raw evidence and start identity.
Final pass, fail and error verdicts remain immutable. The permanent governed
trigger migration changes no historical row and declares a serving floor.

Reviewing an older capture preserves that capture's audit and judgment. It
cannot make a newer attempt pass or discharge replacements on behalf of that
newer attempt. Only the selected current passing successor may record the
existing automatic passing-supersession effect, on the review transaction.

## Definition and proof

Execution and judgment fields determine behavioral currency: method, runner,
verdict path, instructions, expected outcome, executable config, entry surface,
starting state, required completion, capabilities and meaningful ordering.
Display names and explanatory reason labels do not invalidate proof.

An admitted deployment definition is frozen. Grade it against that admitted
definition; live source edits remain source-lineage diagnostics and retain the
explicit refresh boundary. A source replacement does not silently retire an
admitted copy or the source obligation from which it came.

Proof must describe the same selected attempt and subject. Code proof records
the observed build identity; an expected release SHA is not an observation.
Browser capture time never substitutes for observed identity. A build may
prove an accepted landing through verified repository containment.
Terminal settlement checks code/build SHA only for a code subject. Frozen
Machine/mission runners prove the same actual capture through the admitted
case result, baseline, host lease and contract; a direct Machine case uses its
own canonical machine artifact and leased resource without a plan wrapper.
Reviews inherit that identity.
Endpoint Command cases record the URL actually passed to their command and
prove it belongs to the frozen target. Generic hand writers do not stamp an
ambient lane SHA onto these resource subjects. Missing resource proof refuses
with `qa_machine_*` or `qa_endpoint_*`; rerun the named actual case against its
required target. Configuration and document checks retain their appropriate
actual evidence. Do not borrow an old screenshot, passing verdict or unrelated
execution result to complete a current proof chain.

Completion is scoped to target environment and frozen delivery membership.
A cancelled duplicate carrying no QA does not erase an earlier applicable
authoritative delivery. A completed item or delivery stays completed; reads
do not reopen it or rewrite its historical judgments.

## Empty and discharged scopes

These are distinct answers: the applicable workflow requires no QA; an
explicit no-obligation decision exists; every applicable requirement was
legitimately waived or retracted; or required setup is missing. Empty rows alone
do not prove authorization. Keep each disposition and its reason visible.

Requirement aggregation is all-pass. Attempt voting and historical pass rescue
are unsupported. A measured threshold may judge one execution's outcome; it
does not count attempts. See [success policy](success-policy-schema.md).


Integration simulation retains failed reports and all earlier attempts. The
existing PROCEED operation may record a distinct triage discharge only when
the selected report explicitly recommends PROCEED, has no CRITICAL gaps, and
its required follow-up refs exist in the same project. The existing event
ledger records the exact attempt/capture, report digest, accountable actor,
rationale and filed refs. This extends the existing adjudication audit instead
of introducing a new table or approval framework. It does not manufacture a
pass or change the failed report. A newer actual attempt invalidates that
discharge, and summaries expose triage separately from pass and waiver.
