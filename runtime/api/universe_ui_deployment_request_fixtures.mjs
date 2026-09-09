// The deployment-approval shapes a gate card has to tell apart.
//
// Run membership and release contents are different facts, and the cases
// that matter are exactly where they diverge: an item-bound run where they
// coincide, an environment run that owns nothing and ships everything, a
// release that genuinely carries nothing, one whose contents could not be
// determined at all, and a sign-off answered after the release has run.

import { requestRow } from "./universe_ui_inbox_test_support.mjs";

export function deploymentRequestRow(overrides = {}) {
  return requestRow({
    id: 12,
    kind: "deployment_stage_approval",
    subject_type: "deployment_stage",
    subject_key: "run-20260721-014:prod-deploy",
    subject_context: {
      run_id: "run-20260721-014",
      flow: { id: "yoke-hosted-production", name: "yoke-hosted-production" },
      stage: "prod-deploy",
      // The gate sits before the release stage, so approving it lets the
      // pipeline continue into a deploy.
      stage_position: { index: 0, total: 2, remaining: ["release"] },
      batch: {
        item_count: 2,
        items: [
          { item_id: 2712, item_ref: "YOK-2712", title: "Served context window" },
          { item_id: 2707, item_ref: "YOK-2707", title: "Messages address actors" },
        ],
      },
      shipping: {
        release_lineage: "0.1.1+launch.379",
        target_environment: "prod",
        summary: "2 item(s) ship to prod under release lineage 0.1.1+launch.379.",
      },
      // What the run actually carries, derived from release lineage when the
      // request was created. Membership and contents coincide here; the
      // environment-run fixtures below are where they diverge.
      carried: {
        schema: 1,
        derivation: {
          status: "derived",
          contents_known: true,
          reason: "complete",
          recovery: "No action is required.",
          previous_release_lineage: "0.1.0+launch.361",
          release_lineage: "0.1.1+launch.379",
        },
        items: [
          { item_id: 2712, ref: "YOK-2712", commit_shas: ["aa11bb22cc33"] },
          { item_id: 2707, ref: "YOK-2707", commit_shas: ["dd44ee55ff66"] },
        ],
        commits: [],
        warnings: [],
      },
      title: "Deploy to prod — approve the stage",
    },
    ...overrides,
  });
}

// An environment run: the pipeline owns no items, and the release still
// carries every change merged since the last one. A card that reads only
// membership calls this an empty release and asks someone to approve it.
export function environmentRunRequestRow(overrides = {}) {
  const row = deploymentRequestRow(overrides);
  return {
    ...row,
    subject_context: {
      ...row.subject_context,
      batch: { item_count: 0, items: [] },
      shipping: {
        release_lineage: "0.1.2+launch.407",
        target_environment: "stage",
        summary: "0 item(s) ship to stage.",
      },
      carried: {
        schema: 1,
        derivation: {
          status: "derived",
          contents_known: true,
          reason: "complete",
          recovery: "No action is required.",
          previous_release_lineage: "0.1.1+launch.379",
          release_lineage: "0.1.2+launch.407",
        },
        items: [
          { item_id: 2712, ref: "YOK-2712", commit_shas: ["aa11bb22cc33"] },
        ],
        commits: ["9911aa22bb33"],
        warnings: [],
      },
    },
  };
}

// The same environment run on a host that cannot derive its contents. The
// honest answer is the reason and the revision, never an empty release.
export function undeterminedContentsRequestRow(overrides = {}) {
  const row = environmentRunRequestRow(overrides);
  return {
    ...row,
    subject_context: {
      ...row.subject_context,
      carried: {
        schema: 1,
        derivation: {
          status: "empty",
          contents_known: false,
          reason: "project_checkout_unavailable",
          recovery:
            "Register this project's checkout on the deployment machine, "
            + "then retry.",
          release_lineage: "0.1.2+launch.407",
        },
        items: [],
        commits: [],
        warnings: [],
      },
    },
  };
}

// A sign-off stage at the end of a flow: the release has already run, and
// approving completes the run rather than deploying anything.
export function signOffRequestRow(overrides = {}) {
  const row = deploymentRequestRow(overrides);
  return {
    ...row,
    subject_context: {
      ...row.subject_context,
      stage: "approve-result",
      stage_position: { index: 3, total: 4, remaining: [] },
    },
  };
}

// A release whose comparison ran and found nothing. Distinct from one whose
// contents could not be determined at all.
export function emptyReleaseRequestRow(overrides = {}) {
  const row = deploymentRequestRow(overrides);
  return {
    ...row,
    subject_context: {
      ...row.subject_context,
      batch: { item_count: 0, items: [] },
      carried: {
        schema: 1,
        derivation: {
          status: "empty",
          contents_known: true,
          reason: "no_new_commits",
          recovery:
            "No action is required; both runs resolve to the same trunk tree.",
          previous_release_lineage: "0.1.1+launch.379",
          release_lineage: "0.1.1+launch.379",
        },
        items: [],
        commits: [],
        warnings: [],
      },
    },
  };
}
