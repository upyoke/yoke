// What a gate SHOWS the person answering it, for every kind that has
// something to show.
//
// A person asked to record a verdict must be shown what they are deciding
// about, and must be told plainly when there is nothing there. Those two
// cases rendering identically is the defect this module exists to end: a
// request backed by four screenshots and one backed by no evidence at all
// used to reach the approver as the same row.
//
// Both surfaces that draw a gate read it from here, so the Inbox and the
// deployment card describe one decision one way. They frame it differently
// on purpose -- the Inbox is the mailbox end and carries the whole subject,
// while a run card already names its own release and only has to say what
// stopped it -- so the parts each surface needs are exported separately.

import { el } from "./universe_view_support.js";

const MAX_LISTED = 6;

function block(documentNode, parent, className, heading) {
  const node = el(documentNode, "div", className);
  if (heading) node.appendChild(el(documentNode, "div", "gate-block-head", heading));
  parent.appendChild(node);
  return node;
}

function row(documentNode, parent, code, copy) {
  const line = el(documentNode, "div", "gate-block-row");
  line.appendChild(el(documentNode, "code", "gate-block-code", code));
  if (copy) line.appendChild(el(documentNode, "span", "gate-block-copy", copy));
  parent.appendChild(line);
  return line;
}

function overflow(documentNode, parent, total, noun) {
  if (total <= MAX_LISTED) return;
  parent.appendChild(el(
    documentNode,
    "div",
    "gate-block-more",
    `+${total - MAX_LISTED} more ${noun}`,
  ));
}

// The prose that answers "what am I actually saying yes to". Each kind names
// its own consequence, because approving a release, a transition and a QA
// verdict are three different acts.
export function approvalProse(row_) {
  const facts = row_.subject_context || {};
  if (row_.kind === "deployment_stage_approval") {
    const count = Number(facts.batch?.item_count || 0);
    const target = facts.shipping?.target_environment;
    const advance = "Approving advances the pipeline, which is suspended at "
      + "this stage until it resolves.";
    // A run with no recorded items is still shipping something -- bare
    // commits nobody filed work for. Saying it "releases 0 items" reads as
    // if approving were free, which is the opposite of what it means.
    if (!count) {
      return `This run carries no recorded items, so what ships${
        target ? ` to ${target}` : ""
      } is whatever its commits contain. ${advance}`;
    }
    return `This run releases ${count} ${count === 1 ? "item" : "items"} `
      + `together${target ? ` to ${target}` : ""}. ${advance}`;
  }
  if (row_.kind === "lifecycle_transition_approval") {
    return `Moving ${facts.item_ref || "this item"} from ${
      facts.from_stage || "its current stage"
    } to ${facts.to_stage || "the next stage"}. The item's pinned workflow `
      + "version declares this transition gated; nothing advances until you "
      + "decide.";
  }
  if (row_.kind === "qa_needs_review") {
    const requirement = facts.requirement_id;
    return "The agent could not call this pass or fail, so the verdict is "
      + `yours. Approving records a pass against requirement ${
        requirement ?? "under review"
      }, attributed to you.`;
  }
  return "";
}

// The evidence behind an undetermined verdict, counted by type rather than
// described in prose. Both surfaces draw this: a reviewer deciding from a
// run card needs the same answer to "backed by what" as one deciding from
// the Inbox, and a run with no artifacts has to say so in both places.
export function appendEvidence(documentNode, host, facts) {
  const artifacts = Array.isArray(facts.artifacts) ? facts.artifacts : [];
  // evidence_state is the producer's own answer, and it is validated against
  // the artifact count at write time. Trusting it here keeps the reader and
  // the record from disagreeing about whether evidence exists.
  if (facts.evidence_state === "missing" || !artifacts.length) {
    const none = el(documentNode, "div", "gate-evidence-none");
    none.setAttribute("role", "note");
    none.appendChild(el(documentNode, "span", "gate-evidence-warn", "⚠"));
    none.appendChild(el(
      documentNode,
      "span",
      null,
      "No evidence attached. This run recorded no artifacts, so there is "
      + "nothing to review — a pass or fail here would be a verdict on "
      + "nothing.",
    ));
    host.appendChild(none);
    return none;
  }
  const counts = new Map();
  for (const artifact of artifacts) {
    const type = String(artifact.artifact_type || "artifact");
    counts.set(type, (counts.get(type) || 0) + 1);
  }
  const evidence = block(
    documentNode,
    host,
    "gate-evidence",
    `Evidence · ${artifacts.length} artifact${artifacts.length === 1 ? "" : "s"}`,
  );
  for (const [type, count] of counts) {
    const chip = el(documentNode, "span", "gate-evidence-chip");
    chip.appendChild(el(documentNode, "span", "gate-evidence-count", String(count)));
    chip.appendChild(el(documentNode, "span", null, type));
    evidence.appendChild(chip);
  }
  return evidence;
}

function appendQaBody(documentNode, host, facts) {
  if (facts.expected_outcome) {
    const expected = block(
      documentNode, host, "gate-block", "Expected outcome",
    );
    expected.appendChild(el(
      documentNode, "div", "gate-block-copy", String(facts.expected_outcome),
    ));
  }
  if (facts.verdict_reason) {
    const reason = block(documentNode, host, "gate-block", "Why the agent could not decide");
    reason.appendChild(el(
      documentNode, "q", "gate-verdict-reason", String(facts.verdict_reason),
    ));
  }
  appendEvidence(documentNode, host, facts);
}

function appendLifecycleBody(documentNode, host, facts) {
  const changes = facts.branch_changes || {};
  const touched = Array.isArray(changes.touched_files) ? changes.touched_files : [];
  const changed = block(
    documentNode, host, "gate-block", "What changed on the branch",
  );
  if (changes.summary) {
    changed.appendChild(el(
      documentNode, "div", "gate-block-copy", String(changes.summary),
    ));
  }
  if (changes.branch) {
    row(documentNode, changed, String(changes.branch), changes.commit_sha
      ? String(changes.commit_sha).slice(0, 12) : "");
  }
  for (const path of touched.slice(0, MAX_LISTED)) {
    row(documentNode, changed, String(path), "");
  }
  overflow(documentNode, changed, touched.length, "files");
  if (!changes.summary && !touched.length && !changes.branch) {
    changed.appendChild(el(
      documentNode,
      "div",
      "gate-block-copy",
      "No branch changes were recorded for this transition.",
    ));
  }
}

function appendDeploymentBody(documentNode, host, facts) {
  const batch = facts.batch || {};
  const items = Array.isArray(batch.items) ? batch.items : [];
  const count = Number(batch.item_count || items.length);
  // The payload of a deployment approval is the items, not the run id: the
  // approver is blessing N pieces of work, and a run identifier alone never
  // told them what they were shipping.
  const release = block(
    documentNode,
    host,
    "gate-block",
    `In this release · ${count} item${count === 1 ? "" : "s"}`,
  );
  for (const item of items.slice(0, MAX_LISTED)) {
    row(
      documentNode,
      release,
      String(item.item_ref || `item ${item.item_id}`),
      String(item.title || ""),
    );
  }
  overflow(documentNode, release, items.length, "items");
  if (!items.length) {
    release.appendChild(el(
      documentNode,
      "div",
      "gate-block-copy",
      "This run carries no recorded items.",
    ));
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

// Machine approvals draw no body here on purpose: what an approver needs
// beside that decision — the machine, its one-time code, who asked — is the
// Machines page the row already links to, and the subtitle carries it.
const BODY_BUILDERS = {
  qa_needs_review: appendQaBody,
  lifecycle_transition_approval: appendLifecycleBody,
  deployment_stage_approval: appendDeploymentBody,
};

export function appendGateBody(documentNode, wrap, row_) {
  const builder = BODY_BUILDERS[row_.kind];
  const prose = approvalProse(row_);
  if (!builder && !prose) return null;
  const host = el(documentNode, "div", "gate-body");
  if (prose) {
    const what = el(documentNode, "div", "gate-what");
    what.appendChild(el(
      documentNode, "span", "gate-what-label", "What you are approving",
    ));
    what.appendChild(el(documentNode, "span", "gate-what-copy", prose));
    host.appendChild(what);
  }
  if (builder) builder(documentNode, host, row_.subject_context || {});
  wrap.appendChild(host);
  return host;
}

export const decisionGateBody = { appendEvidence, appendGateBody, approvalProse };
