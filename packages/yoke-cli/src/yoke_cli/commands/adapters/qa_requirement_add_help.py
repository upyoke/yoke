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
    "[--host-baseline NAME] "
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

A case that runs on a Test Machine declares the state it starts from:
--host-baseline names a registered baseline the runner resets to first.
Use shell-preconfigured when the case needs Yoke. Every host_control
case runs on a Test Machine. Set method_config.os and optional capability_tags
(a JSON array such as ["arch:x64"]) to select a verified, healthy match.
Test Machines of one kind are identical, so a case never names a host. A case
needing several hosts lists OS slots in method_config.test_machines, such as
[{"os":"linux"},{"os":"macos","driver":true}], with exactly one driver; its
capability_tags is an object from slot OS to tags, such as
{"macos":["macos:15"]}. A Command that declares method_config.os
or slots runs on a Test Machine and also requires --host-baseline. An
agent_mission with no OS, slots, host tags or baseline runs on the controller.
--test-machine on a run picks a host for that run only. A replacement selects
afresh, and a resume keeps affinity within its execution history.
A case added on its own belongs to no plan, so it cannot inherit a preceding
case's machine; author that chain in a plan.

--workflow-transition names a stage of the item's pinned workflow; read it
from `yoke workflows item get PREFIX-N --json` (Dash: reviewing-implementation).
An epic task's case is its implementation review: seed it with
`yoke workflow-item epic-task review-seed --epic PREFIX-N --task-num K`.
Exit codes: 0 success, 1 dispatch failure (e.g. claim_required, a closed
run, a stage the run does not declare), 2 usage.
"""


__all__ = ["QA_REQUIREMENT_ADD_HELP_DEEP", "QA_REQUIREMENT_ADD_USAGE"]
