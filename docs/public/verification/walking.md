# Walking QA missions

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Walking QA missions
<!-- /yoke:breadcrumbs -->

Walk each exploratory mission in the session's main thread. Use the mission's
instructions and expected outcome to explore the declared surfaces, attach
evidence as you go, and record your verdict from what you observed.

## Inputs

The dispatch carries the mission, its good outcome, and the exact commands for
this walk: `walk-start`, `host-command`, `host-copy`, browser setup and step,
`artifact-add` with its artifact limit, and `walk-end`. Use those commands
exactly. When a human replies to a gate, read their answer and verify the
action before continuing at the resume point you sent.

A hostless mission uses controller tools only: no lease, walk-start, walk-end
or host-command. For a host mission, use the driver in the dispatch. The
scheduler selects by OS and capability tags when the case is portable. A named
driver requires a case-specific reason. A resume keeps its execution's host
affinity. A replacement uses its new dispatch even if the old attempt used
another host.

## Method

Restate the mission boundary in one sentence, inventory the declared
substrates, and form questions that test the good outcome. Choose the order
yourself; landmarks are territory, not steps. Follow surprises inside the
boundary, never past it. For each finding separate observed from expected
behavior and give impact, the smallest reproduction, and confidence
(established, probable or unverified). Rank by user impact and fix leverage.
A clean walk backed by evidence is a valid result; never manufacture findings.
Missing access is a setup failure to report, not permission to change policy.
Never attach walk data to records that existed before the walk; create your
own and retire them during Cleanup. If the mission needs unavailable setup,
create owned fixtures or stop with setup-failure proof attached as `diagnostic`.

## Hosts

Run walk-start before the first host command. If it returns
`mission_walk_already_started`, continue with host-command on the existing
scratch. Run walk-end first if you intend to reset and start again. For other
start failures, record the blocker and its recovery. Run host commands only through the dispatch's `yoke qa
mission host-command ... -- ARGV...`, called directly rather than from your own
script, in the foreground with a tool timeout at least as long as the call's.
On Codex, set `yield_time_ms` at or above the call's timeout in milliseconds
so the foreground call delivers the next tool result and any messages.
For a companion host, add `--test-machine NAME` before `--`, naming one of the
leased hosts the dispatch reports; without it the command goes to the driver. Every declared
lease stays held. Never reach a host through SSH or copy credentials into a
shell. For macOS window-server or login-keychain work add `--gui-session`.
Copy a file back with the dispatch's `host-copy --from TARGET_PATH --to
LOCAL_PATH`. Install packages only through host-command so the walk's journal
records them. A display-capture failure, audit-session refusal, or OAuth that
looks expired while its files are unchanged means the wrong session context:
retry through `--gui-session` before you report broken credentials.

Pipe a secret on stdin where the product accepts it; otherwise stage it only in
the dispatch's owner-only scratch directory, never loose under `/tmp` or home.
Never read a secret's content or put one in a report.

For session-start proof, read and record the delivered orientation marker as
`.yoke/docs/verification/exploration-evidence.md` teaches.

### Occupied hosts and continuation

When another mission holds a required host, leave the host alone and submit
`host_wait` through the review bundle with the test machine name and the
holder's lease evidence. Resume when the host is available.

On `agent_mission_access_failed`, read the refusal. When it names a `yoke qa
plan run ... --continue-mission` continuation, run exactly that and resume the
held state; an ordinary plan run resets the baseline and wipes partial work.
Say in the report that you continued a settled execution and why. When it
names server cleanup still owed, run that cleanup, then return.
On `mission_walk_stopped`, walk nothing more: finish Cleanup on the held lease,
then run walk-end.

## Browser and desktop

When the dispatch names browser identities, run each identity's `yoke browser
verify` before browsing as it, and use the managed setup and step commands with
`--identity NAME` (`--page NAME` keeps several pages open for one identity).
For an expired site sign-in, run `yoke browser authorize --identity NAME` on
that host and sign in again yourself. Without named identities, use the
managed browser only if this walk installed Yoke; otherwise open each page with
the brief's `yoke browser open` command, a visible window of the machine's
operator identity, and drive it through screenshot and keystroke host
commands. Never use the stock desktop browser. Never install Yoke
to get a browser, and never save or restore a browser profile. Name in the
report the host, the browser actually used, the identity and the URL from the
commands you ran.

Native windows, dialogs, Terminal, keychain and app handoffs need a visible GUI
session through the dispatch's desktop control; never infer them from SSH.
On a native Windows host, drive any app with `yoke qa mission desktop` and the
dispatch's mission flags: `windows` lists windows, then `focus`, `click`
(`--x/--y` relative to the window, or `--name`/`--automation-id`/
`--control-type` with `--index N` when several match), `type --text-stdin`
with the text piped on stdin, `keys --keys 'ctrl+l'` and `read` act on one
window named by `--title`, `--process` or `--handle`. Launch apps with
`host-command --gui-session` and look with `yoke test-machine screenshot`;
no RDP session or Windows App is needed. Each refusal names its code and
recovery; never type a password or token through it.
For a person at a workstation, name `yoke test-machine desktop-access --view`;
it opens every registered desktop, macOS through Screen Sharing.

## Human gates

Drive the declared GUI, approve ordinary consent prompts, choose the
declared identity, and handle device codes in the host's signed-in browser.
Preserve the behavior under test, including browser approval when the case
tests it. Record each workaround and its effect on the tested behavior.

At a password, 2FA or payment step that requires a person, record evidence
without exposing credentials. Verify the host, browser, profile, target URL
and live access route. Preview `yoke say --preview --steering --json`. If the
preview says `delivered`, send to `--steering` and check the receipt. Otherwise,
look up the item owner with `yoke items get PREFIX-N owner`, preview
`yoke say --preview --actor ACTOR --json`, and send to that actor. Report a
refusal or unresolved owner as a blocker.

Name the plan, execution, requirement, action, access route and resume point.
Ask for a reply using `yoke say --session YOUR_SESSION_ID --stdin`. Run
`yoke sessions touch --mode parked --reason qa-human-gate` and end the turn.
The parked session protects a walking execution from stale abort for inactivity.
The host lease can still expire at its configured `qa_host_idle_hold_minutes`.
When the answer arrives, verify the human action and continue at the recorded
resume point on the held lease. A mission needing a test message sends it from
the Test Machine's own Yoke identity using host-command.

## Stage fixtures

Keep executions, artifacts and verdicts on the dispatch's production
connection; use a stage connection only for disposable fixtures. Run fixture
claim, lane, merge and cancel commands from a child harness started in the
fixture checkout with `YOKE_ENV=<stage connection>`, so its own opening hook
registers its session on stage; confirm with `yoke sessions identity` before
claiming. `--env` from the production session does not register it there.
Never reuse the production session, pass another session id or register a
session by hand; a refused route is a finding. Match controller and candidate
versions as `.yoke/docs/verification/candidate-controller.md` teaches.

## Cleanup

Clean up the walk's repositories, accounts and other test fixtures with the
product's own commands before walk-end, even when the walk stops early. The
Test Machine's fresh-host reset retires the lab user's registered Machine
before wiping its identity. Inherit cases keep that identity until a reset.
Host cleanup such as `yoke project uninstall` needs the lease. Run server
cleanup such as `yoke --env ENV projects retire` even after access is lost.
Create GitHub fixture
repositories with `gh repo create OWNER/NAME --private`, record every exact
`OWNER/NAME` (including one the product creates), and delete each with
`gh repo delete OWNER/NAME --yes`. Never delete upstream or pre-existing
resources. Then run walk-end: it removes the scratch directory and restores the
starting state. Report both, and report anything still present; a failed
walk-end is a finding against this walk.

## Evidence

Screens, DOM reads and command output guide the walk and are disposable. Attach
deliberate proof only for ranked findings and human gates, within the artifact
limit, through the dispatch's artifact-add recipe. Attach bytes, never a
test-host path.
On a clean walk, attach one deliberate proof of the good outcome as `evidence`
before submitting the verdict, within the same artifact limit.
Attach setup-blocker proof as `diagnostic` so a setup-only stop settles without
human review.

## Report and verdict

Report the subject, execution, host or controller, and each case's verdict
with its evidence IDs. Include ranked findings, workarounds and their effect,
remaining unknowns, and cleanup or restore receipts. For non-mission cases
read the supplied capture and record the verdict the same way.

In each pass or fail rationale cite `artifact N` using an artifact ID from
that case. When the case has no artifacts, cite `run N` using its capture run
ID. Submit one verdict row per case through the bundle's review-submit command.
