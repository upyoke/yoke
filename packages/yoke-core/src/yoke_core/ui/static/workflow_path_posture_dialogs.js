import { renderWorkflowDialog } from "./workflow_view_primitives.js";

export function renderPathClaimsDialog(
  documentNode,
  dialogHost,
  workflow,
  enabled,
  closeDialog,
  mutation,
  load,
) {
  const name = workflow.name || workflow.id;
  const names = `${name}es`;
  const dialog = {
    title: `${enabled ? "Turn on" : "Turn off"} path claims`,
    subtitle: enabled
      ? `Enable path claims for new ${name} items.`
      : `Return new ${name} items to claim-less by default.`,
    lines: [
      {
        title: "What this does",
        description:
          `reserves the files a ${name} will touch, so overlapping work ` +
          "serializes through the claim machinery instead of colliding at merge.",
      },
      {
        title: "Default (off)",
        description:
          `path claims are off by default. The path survey is a separate ` +
          "posture knob and is on by default: it surveys anticipated " +
          "conflicts, works in an isolated worktree, and re-checks at " +
          "merge without registering every path it wants to change.",
      },
      {
        title: "Turn on when",
        description:
          `you like the reduced overhead of ${names}, but they collide with ` +
          "each other and waste time resolving conflicts or even break things.",
      },
    ],
    impact:
      `Editing creates a new version of the ${name} workflow in your Yoke ` +
      `universe. Items already underway ` +
      `stay pinned to v${workflow.current_version} and are unaffected.`,
    confirmText: `${enabled ? "Turn on" : "Turn off"} path claims`,
    cancel: closeDialog,
    confirm: async () => {
      await mutation("workflows.policy_defaults.publish", {
        workflow_id: workflow.id,
        expected_current_version: Number(workflow.current_version),
        path_claims_default: enabled,
      });
      closeDialog();
      await load();
    },
  };
  renderWorkflowDialog(documentNode, dialogHost, dialog);
}

export function renderPathSurveyDialog(
  documentNode,
  dialogHost,
  workflow,
  enabled,
  closeDialog,
  mutation,
  load,
) {
  const name = workflow.name || workflow.id;
  const dialog = {
    title: `${enabled ? "Turn on" : "Turn off"} path survey`,
    subtitle: enabled
      ? `Enable the path survey for new ${name} items.`
      : `Let new ${name} items skip the path survey by default.`,
    lines: [
      {
        title: "What this does",
        description:
          `checks the files a ${name} expects to touch, reports a clear ` +
          "or blocked verdict with the declared-path fingerprint, and " +
          "re-checks that fingerprint immediately before merge. It does " +
          "not reserve those files.",
      },
      {
        title: "Default (on)",
        description:
          "the path survey runs before execution and keeps the landscape " +
          "check visible beside path claims, which default off and remain " +
          "a separate coordination choice.",
      },
      {
        title: "Turn off when",
        description:
          `the ${name} work is low-collision and the extra landscape check ` +
          "does not justify its coordination overhead.",
      },
    ],
    impact:
      `Editing creates a new version of the ${name} workflow in your Yoke ` +
      `universe. Items already underway stay pinned to v${workflow.current_version} ` +
      "and are unaffected.",
    confirmText: `${enabled ? "Turn on" : "Turn off"} path survey`,
    cancel: closeDialog,
    confirm: async () => {
      await mutation("workflows.policy_defaults.publish", {
        workflow_id: workflow.id,
        expected_current_version: Number(workflow.current_version),
        path_survey_default: enabled,
      });
      closeDialog();
      await load();
    },
  };
  renderWorkflowDialog(documentNode, dialogHost, dialog);
}
