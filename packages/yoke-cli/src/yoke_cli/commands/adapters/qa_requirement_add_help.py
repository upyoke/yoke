"""Usage and deep help for ``yoke qa requirement add``."""

from __future__ import annotations

QA_REQUIREMENT_ADD_USAGE = (
    "yoke qa requirement add (--item PREFIX-N | --deployment-run RUN-ID) "
    "(--qa-kind KIND | --method-id METHOD) "
    "--qa-phase PHASE [--target-env E] [--blocking-mode M] "
    "[--requirement-source S] [--success-policy all-pass|JSON] "
    "[--required-capability KIND ...] [--suite-id ID] "
    "[--instructions TEXT | --instructions-file PATH | --stdin] "
    "[--expected-outcome TEXT | --expected-outcome-file PATH] [--method-config JSON] "
    "[--host-baseline NAME | --starting-state as_is "
    "--starting-state-reason TEXT] "
    "[--workflow-transition STAGE] [--deployment-stage STAGE] "
    "[--deployment-member-item PREFIX-N] [--project P] [--session-id S] [--json]"
)

QA_REQUIREMENT_ADD_HELP_DEEP = """\
Add one QA case to the item or deployment run you name.

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

Manual AC review credits verification requirements at their pinned item QA
gate. A blocking post_deploy row without an executable method refuses as
requirement_proof_required: attach the proving executable plan case, or name a
registered method with complete instructions, expected outcome and config.

Worked examples:

  yoke qa requirement add --item YOK-N \\
    --qa-kind ac_verification --qa-phase verification \\
    --blocking-mode blocking --requirement-source ac_derived \\
    --workflow-transition reviewing-implementation

  yoke qa requirement add --item YOK-N \\
    --method-id browser-inspection --qa-phase verification \\
    --instructions "Open the login route and capture its ready state." \\
    --expected-outcome "The login form is aligned and usable." \\
    --method-config '{"color_scheme":"dark","steps":[{"action":"navigate","route":"/login"},
      {"action":"screenshot","capture":true,"label":"login"}]}' \\
    --workflow-transition reviewing-implementation

  yoke qa requirement add --deployment-run run-YYYYMMDD-NNN \\
    --method-id browser-inspection --qa-phase post_deploy \\
    --deployment-stage stage-smoke \\
    --instructions "Open the released home route and capture it." \\
    --expected-outcome "The home page renders the new build." \\
    --method-config '{"steps":[{"action":"navigate","route":"/"},
      {"action":"screenshot","capture":true,"label":"home"}]}'

Browser method config:

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
Full configuration: verification/browser-targets.md#method-configuration.

A machine-run case (host_control or agent_mission method) declares the Test
Machine state it starts from: --host-baseline names a registered baseline the
runner resets to and restores afterwards, or --starting-state as_is with
--starting-state-reason runs on the machine as found. An undeclared machine
case is refused. A case added on its own belongs to no plan, so it cannot
inherit a preceding case's machine; author that chain in a plan.

--workflow-transition names a stage of the item's pinned workflow; read it
from `yoke workflows item get PREFIX-N --json` (Dash: reviewing-implementation).
An epic task's case is its implementation review: seed it with
`yoke workflow-item epic-task review-seed --epic PREFIX-N --task-num K`.
Exit codes: 0 success, 1 dispatch failure (e.g. claim_required, a closed
run, a stage the run does not declare), 2 usage.
"""


__all__ = ["QA_REQUIREMENT_ADD_HELP_DEEP", "QA_REQUIREMENT_ADD_USAGE"]
