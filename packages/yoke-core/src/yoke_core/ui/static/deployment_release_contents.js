// What a deployment run actually puts into an environment.
//
// Two different facts get confused here, and the confusion is expensive. Run
// MEMBERSHIP is which work items the pipeline owns and will move to done. Run
// CONTENTS is which source changes ship. For an item-bound run they coincide;
// for an environment run membership is empty while the release still carries
// every change merged since the last one, so a card built from membership
// told an approver a release contained nothing and asked them to bless it.
//
// The contents answer is derived from release lineage at the moment the
// approval request is created and frozen into its snapshot, so this module
// only reads what the decision already recorded.

import { el } from "./universe_view_support.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { block, MAX_LISTED, overflow, row } from "./gate_block_layout.js";

// What the release actually contains, preferring the derived answer over run
// membership. Membership is which items the pipeline OWNS; an environment run
// owns none while shipping every change merged since the last release, so a
// card built from membership alone reported an empty release that was not.
export function releaseContents(facts, projectId = null) {
  const itemHref = (ref) => (
    ref ? itemDrillInHref({ projectId, publicRef: ref }) : null
  );
  const carried = facts.carried;
  const derived = Array.isArray(carried?.items) ? carried.items : [];
  const bare = Array.isArray(carried?.commits) ? carried.commits : [];
  if (carried?.derivation?.contents_known) {
    return {
      source: "derived",
      noun: "change",
      count: derived.length + bare.length,
      entries: [
        ...derived.map((entry) => ({
          label: String(entry.ref || `item ${entry.item_id}`),
          detail: `${(entry.commit_shas || []).length} commit(s)`,
          href: itemHref(entry.ref),
        })),
        ...bare.map((sha) => ({
          label: String(sha).slice(0, 12),
          detail: "commit with no item reference",
          href: null,
        })),
      ],
      reason: "",
      recovery: "",
    };
  }
  const items = Array.isArray(facts.batch?.items) ? facts.batch.items : [];
  if (!carried) {
    // A snapshot frozen before release contents were derived. It knows its
    // membership and nothing else, so it reports exactly that.
    return {
      source: "membership",
      noun: "item",
      count: items.length,
      entries: items.map((item) => ({
        label: String(item.item_ref || `item ${item.item_id}`),
        detail: String(item.title || ""),
        href: itemHref(item.item_ref),
      })),
      reason: "",
      recovery: "",
    };
  }
  return {
    source: "unavailable",
    noun: "change",
    count: 0,
    entries: [],
    reason: String(carried.derivation?.reason || "reason not recorded"),
    recovery: String(carried.derivation?.recovery || ""),
  };
}

export function appendDeploymentBody(context, host, facts, projectId = null) {
  const documentNode = context.document;
  const contents = releaseContents(facts, projectId);
  const release = block(
    documentNode,
    host,
    "gate-block",
    `In this release · ${contents.count} ${contents.noun}${
      contents.count === 1 ? "" : "s"
    }`,
  );
  for (const entry of contents.entries.slice(0, MAX_LISTED)) {
    row(documentNode, release, entry.label, entry.detail, entry.href);
  }
  overflow(documentNode, release, contents.entries.length, `${contents.noun}s`);
  if (contents.source === "unavailable") {
    // Never silence: an approver who is not told the derivation could not run
    // reads an empty list as an empty release. A release that genuinely
    // carries nothing is a different fact and gets its own line below.
    release.appendChild(el(
      documentNode,
      "div",
      "gate-block-copy",
      `Release contents could not be determined (${contents.reason}). `
      + `${contents.recovery}`,
    ));
  } else if (contents.source === "derived" && !contents.count) {
    release.appendChild(el(
      documentNode,
      "div",
      "gate-block-copy",
      "This release carries no new commits since the previous one.",
    ));
  }
  // Membership stays visible beside the contents when both exist: it is who
  // the pipeline will move to done, which is a different fact from what ships.
  const itemHref = (ref) => (
    ref ? itemDrillInHref({ projectId, publicRef: ref }) : null
  );
  const linked = Array.isArray(facts.batch?.items) ? facts.batch.items : [];
  if (contents.source === "derived" && linked.length) {
    const owned = block(
      documentNode, host, "gate-block", `Linked items · ${linked.length}`,
    );
    for (const item of linked.slice(0, MAX_LISTED)) {
      row(
        documentNode,
        owned,
        String(item.item_ref || `item ${item.item_id}`),
        String(item.title || ""),
        itemHref(item.item_ref),
      );
    }
    overflow(documentNode, owned, linked.length, "items");
  }
  // The lineage, and only the lineage: the count and the destination are
  // already the first thing the approver reads, and repeating them under
  // the item list is how "0 items" ends up asserted twice on one card.
  const lineage = (facts.shipping || {}).release_lineage;
  if (lineage) {
    release.appendChild(el(
      documentNode, "div", "gate-block-more", `release ${lineage}`,
    ));
  }
}

export const deploymentReleaseContents = {
  appendDeploymentBody,
  releaseContents,
};
