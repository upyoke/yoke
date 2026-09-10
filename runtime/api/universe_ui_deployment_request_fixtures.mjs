// The deployment-approval shapes a gate card has to tell apart.
//
// Run membership and release contents are different facts, and the cases
// that matter are exactly where they diverge: an item-bound run where they
// coincide, an environment run that owns nothing and ships everything, a
// release that genuinely carries nothing, one whose contents could not be
// determined at all, and a sign-off answered after the release has run.
//
// One more pair sits beside those: a gate that deploys nothing at all, and a
// real production release that happens to carry nothing. They look alike from
// membership and they read alike from a flow name, so every fixture carries
// the classification the producer froze rather than letting the card guess.

import { requestRow } from "./universe_ui_inbox_test_support.mjs";

// The producer writes the title from the classification, so a fixture that
// disagreed with its own release_effect would test a shape nothing produces.
function withEffect(context, effect) {
  return { ...context, release_effect: effect, title: effect.headline };
}

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
      // Named runners, a named destination and real contents: a release.
      release_effect: {
        deploys: true,
        headline: "Deploy to prod — approve the prod-deploy stage",
        effect: "",
        basis: [
          "Deploying stages: release runs core-container-deploy.",
          "The flow targets prod.",
          "This run carries source changes and linked work items.",
        ],
      },
      title: "Deploy to prod — approve the prod-deploy stage",
    },
    ...overrides,
  });
}

// An approval-only gate: every stage runs human-approval or auto, the flow
// names no destination, and the run carries nothing. Only all three together
// earn the classification — the flow's name is prose and proves nothing, so
// the practice purpose this sample flow was authored for reaches the reader
// through that authored name and never through the derivation.
export function approvalOnlyRequestRow(overrides = {}) {
  const row = deploymentRequestRow(overrides);
  return {
    ...row,
    subject_context: withEffect(
      {
        ...row.subject_context,
        run_id: "run-20260910-003",
        flow: {
          id: "approval-practice-role-review",
          name: "Practice: role approval — deploys nothing",
        },
        stage: "review-example",
        stage_position: { index: 0, total: 2, remaining: ["finish-example"] },
        batch: { item_count: 0, items: [] },
        shipping: {
          release_lineage: null,
          target_environment: "merge-only",
          summary: "0 item(s) ship to merge-only.",
        },
        carried: {
          schema: 1,
          derivation: {
            status: "empty",
            contents_known: true,
            reason: "no_release_lineage",
            recovery: "No action is required; this run ships nothing.",
          },
          items: [],
          commits: [],
          warnings: [],
        },
      },
      {
        deploys: false,
        headline: "Approval only — deploys nothing",
        effect:
          "Resolving this records your decision and lets the run finish. "
          + "Nothing is built, released, or promoted, no environment changes, "
          + "and no work item moves.",
        basis: [
          "No stage in this flow can deploy: every stage runs human-approval "
          + "or auto.",
          "The flow names no target environment or tier.",
          "This run carries no source change and owns no work item.",
        ],
      },
    ),
  };
}

// An environment run: the pipeline owns no items, and the release still
// carries every change merged since the last one. A card that reads only
// membership calls this an empty release and asks someone to approve it.
export function environmentRunRequestRow(overrides = {}) {
  const row = deploymentRequestRow(overrides);
  return {
    ...row,
    subject_context: withEffect({
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
    }, {
      deploys: true,
      headline: "Deploy to stage — approve the prod-deploy stage",
      effect: "",
      basis: [
        "Deploying stages: release runs core-container-deploy.",
        "The flow targets stage.",
        "This run carries source changes.",
      ],
    }),
  };
}

// The same environment run on a host that cannot derive its contents. The
// honest answer is the reason and the revision, never an empty release.
export function undeterminedContentsRequestRow(overrides = {}) {
  const row = environmentRunRequestRow(overrides);
  return {
    ...row,
    subject_context: withEffect({
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
    }, {
      deploys: true,
      headline: "Deploy to stage — approve the prod-deploy stage",
      effect: "",
      basis: [
        "Deploying stages: release runs core-container-deploy.",
        "The flow targets stage.",
        "This run's contents could not be derived, so what it carries is "
        + "unknown.",
      ],
    }),
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
// contents could not be determined at all, and — the trap this fixture holds
// open — indistinguishable from an approval-only gate by membership alone. It
// targets prod, so it is a release however little it carries.
export function emptyReleaseRequestRow(overrides = {}) {
  const row = deploymentRequestRow(overrides);
  return {
    ...row,
    subject_context: withEffect({
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
    }, {
      deploys: true,
      headline: "Deploy to prod — approve the prod-deploy stage",
      effect: "",
      basis: [
        "Deploying stages: release runs core-container-deploy.",
        "The flow targets prod.",
      ],
    }),
  };
}
