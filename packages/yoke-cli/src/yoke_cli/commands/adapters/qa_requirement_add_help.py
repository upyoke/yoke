"""Usage and deep help for ``yoke qa requirement add``."""

from __future__ import annotations

QA_REQUIREMENT_ADD_USAGE = (
    "yoke qa requirement add (--item PREFIX-N | --deployment-run RUN-ID) "
    "(--qa-kind KIND | --method-id METHOD) "
    "--qa-phase PHASE [--target-env E] [--blocking-mode M] "
    "[--requirement-source S] [--success-policy JSON-OR-TEXT] "
    "[--required-capability KIND ...] [--suite-id ID] "
    "[--instructions TEXT | --instructions-file PATH | --stdin] "
    "[--expected-outcome TEXT | --expected-outcome-file PATH] "
    "[--host-baseline NAME | --starting-state as_is "
    "--starting-state-reason TEXT] "
    "[--workflow-transition STAGE] [--deployment-stage STAGE] "
    "[--deployment-member-item PREFIX-N] [--session-id S] [--json]"
)

QA_REQUIREMENT_ADD_HELP_DEEP = """\
Insert one qa_requirements row against the subject you name.

  --item PREFIX-N         the case is that item's own verification.
                          Claim-gated: the calling session must hold the
                          item's active work claim, and the case names the
                          pinned workflow stage it governs.
  --deployment-run RUN-ID the case is that release's own check. Authorized
                          by the run's project scope; no workflow stage,
                          because the run owns the context. Optionally
                          scoped to one --deployment-stage, and within it
                          one --deployment-member-item the run carries.
                          A run that has already finished is refused: its
                          evidence is closed. The case must name a method
                          (--method-id) and a bindable target
                          (--deployment-stage for frozen run/stage
                          authority, or --target-env). Existing unbound
                          member cases recover on `yoke qa case run
                          --requirement-id N`; do not add-item onto a
                          frozen run and do not attach a plan.

Worked examples:

  yoke qa requirement add --item YOK-N \\
    --qa-kind ac_verification --qa-phase verification \\
    --blocking-mode blocking --requirement-source ac_derived \\
    --workflow-transition reviewed-implementation

  yoke qa requirement add --item YOK-N \\
    --method-id browser-inspection --qa-phase verification \\
    --instructions "Open the login route and capture its ready state." \\
    --expected-outcome "The login form is aligned and usable." \\
    --method-config '{"color_scheme":"dark","steps":[{"action":"navigate","route":"/login"},
      {"action":"screenshot","capture":true,"label":"login"}]}' \\
    --workflow-transition reviewed-implementation

  yoke qa requirement add --deployment-run run-YYYYMMDD-NNN \\
    --method-id browser-inspection --qa-phase post_deploy \\
    --deployment-stage stage-smoke \\
    --instructions "Open the released home route and capture it." \\
    --expected-outcome "The home page renders the new build." \\
    --method-config '{"steps":[{"action":"navigate","route":"/"},
      {"action":"screenshot","capture":true,"label":"home"}]}'

Flag matrix:

Browser method_config.color_scheme optionally selects light or dark for this
case's owned page before navigation, fixed across steps/navigation/reload.
Omit it for the ordinary browser preference; use separate cases for both modes.
Run and screenshot metadata keep requested and observed prefers-color-scheme.
Invalid values, failed emulation, missing observations and mismatches refuse
by name: correct the setting or repair the daemon and rerun. Media preference
proves browser input; normal assertions/visual judgment still judge the app.
Browser method_config.browser_identity names the declared project identity
the case runs as (default `default`); an agent mission's
method_config.browser_identities lists the identities its walker verifies
signed in before browsing (`yoke browser verify --identity NAME`).
Full configuration: reference/browser-scenarios.md, Method configuration.

  flag                        required  default    value shape
  --item                      one-of    —          PREFIX-N
  --deployment-run            one-of    —          run-YYYYMMDD-NNN
  --deployment-stage          no        —          run-attached: pinned stage name
  --deployment-member-item    no        —          run-attached: member PREFIX-N (needs stage)
  --qa-kind                   one-of    —          ad hoc legacy/plumbing discriminator
  --method-id                 one-of    —          registered QA method id
  --qa-phase                  yes       —          verification | post_deploy | manual_acceptance
  --target-env                no        —          env name
  --blocking-mode             no        blocking   blocking | non_blocking
  --requirement-source        no        explicit   explicit | seeded_default | ac_derived | flow_derived
  --instructions              method    —          what the case executes
  --expected-outcome          method    —          observable passing outcome
  --method-config             method    —          method-specific JSON object
  --host-baseline             machine   —          registered baseline reset before the case
  --starting-state            machine   —          as_is (runs on the machine as found)
  --starting-state-reason     as_is     —          why the machine as found is the start
  --workflow-transition      item      —          pinned workflow stage id
  --success-policy            no        —          aggregate/ad hoc policy
  --required-capability       no        —          repeatable capability kind
  --suite-id                  no        —          suite id string
  --session-id                no        ambient    opaque session id (operator-debug)
  --json                      no        false      flag (typed envelope on stdout)

A machine-run case (host_control or agent_mission method) declares the Test
Machine state it starts from: --host-baseline names a registered baseline the
runner resets to and restores afterwards, or --starting-state as_is with
--starting-state-reason runs on the machine as found. An undeclared machine
case is refused. A case added on its own belongs to no plan, so it cannot
inherit a preceding case's machine; author that chain in a plan.

Epic-task attachment: operator-debug domain CLI only.
Exit codes: 0 success, 1 dispatch failure (e.g. claim_required, a closed
run, a stage the run does not declare), 2 usage.
"""


__all__ = ["QA_REQUIREMENT_ADD_HELP_DEEP", "QA_REQUIREMENT_ADD_USAGE"]
