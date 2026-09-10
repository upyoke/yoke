import { el } from "./universe_view_support.js";
import { block, MAX_LISTED, overflow, row } from "./gate_block_layout.js";
import {
  decisionEligibility,
  decisionOrigin,
  decisionSummary,
} from "./inbox_presentation.js";
import {
  appendDeploymentBody,
  releaseContents,
} from "./deployment_release_contents.js";
import { artifactEvidenceCard } from "./qa_evidence_artifact_view.js";

// A request frozen before the consequence was recorded knows its run, flow
// and stage and nothing about what resolving it reaches. Saying so is the
// only honest reading: the title it stored was composed from a shipping
// destination that may have been the no-destination label.
const LEGACY_UNRECORDED_EFFECT = "This request was recorded before what "
  + "resolving it deploys was, so the request itself does not say. Read the "
  + "run's flow before answering.";

// What this run carries, and what resolving THIS stage does to it. Not every
// gated stage precedes a deploy: a sign-off at the end of a flow is answered
// after the release has already run, so the effect is read from the stage's
// own position rather than assumed.
function deploymentProse(facts) {
  // A gate that reaches no environment, and one whose consequence could not
  // be established, each say so in their own words. Both sentences are frozen
  // into the request beside the classification, so the reader is never told a
  // run deploys nothing because its name or its empty batch suggested it, and
  // never told an unproven one deploys.
  const recorded = facts.release_effect;
  if (!recorded) return LEGACY_UNRECORDED_EFFECT;
  if (recorded.consequence !== "deploys") return String(recorded.effect || "");
  const contents = releaseContents(facts);
  const target = facts.shipping?.target_environment;
  const remaining = facts.stage_position?.remaining;
  const carries = contents.source === "unavailable"
    ? `This run's contents could not be determined (${contents.reason}), so `
      + `what it carries${target ? ` to ${target}` : ""} is whatever commit ${
        facts.shipping?.release_lineage || "its lineage names"
      } contains.`
    : contents.count
      ? `This run carries ${contents.count} ${
        contents.count === 1 ? contents.noun : `${contents.noun}s`
      }${target ? ` to ${target}` : ""}.`
      : `This run carries no new ${contents.noun}s${
        target ? ` to ${target}` : ""
      }.`;
  // The run is suspended AT this stage, so whatever the flow names after it
  // is exactly what approving lets the pipeline continue into. Nothing after
  // it means approving completes the run rather than starting a deploy.
  const effect = !Array.isArray(remaining)
    ? "Approving advances the pipeline, which is suspended at this stage "
      + "until it resolves."
    : remaining.length
      ? `The pipeline is suspended at ${facts.stage || "this stage"} and `
        + `continues into ${remaining.join(", ")} once you resolve it.`
      : `${facts.stage || "This stage"} is the last stage in this flow, so `
        + "every earlier stage has already run: approving completes the run "
        + "rather than starting another deploy.";
  return `${carries} ${effect}`;
}

// The prose that answers "what am I actually saying yes to". Each kind names
// its own consequence, because approving a release, a transition and a QA
// verdict are three different acts.
export function approvalProse(row_) {
  const facts = row_.subject_context || {};
  if (row_.kind === "deployment_stage_approval") {
    return deploymentProse(facts);
  }
  if (row_.kind === "lifecycle_transition_approval") {
    // An item reaching its last stage is a record of state, not a release.
    // Reading "approve the done transition" as permission to ship is the
    // confusion this sentence exists to remove: no deployment flow consults
    // this decision, and approving it puts nothing into any environment.
    return `Moving ${facts.item_ref || "this item"} from ${
      facts.from_stage || "its current stage"
    } to ${facts.to_stage || "the next stage"}. This records the item's `
      + "state only — it deploys nothing and releases nothing to any "
      + "environment.";
  }
  if (row_.kind === "qa_needs_review") {
    const subject = facts.subject || {};
    const requirement = facts.requirement_id ?? "under review";
    const verdict = "The agent could not call this pass or fail, so the "
      + `verdict is yours. Approving records a pass against requirement ${
        requirement
      }, attributed to you.`;
    // `qa_phase` says how the check was DECLARED, never that a release has
    // happened: a run still waiting at its approval stage already carries
    // post-deploy requirements. So the sentence names what was checked and
    // what a verdict can reach, and claims nothing about what has shipped.
    if (subject.kind === "deployment_run") {
      return `${verdict} This check is declared ${
        subject.qa_phase || "on this run"
      } against ${subject.deployment_run_id || "the run"}: a verdict here can `
        + "gate that run's completion, and cannot undo code the run has "
        + "already deployed.";
    }
    return `${verdict}${
      subject.item_ref ? ` It was checked against ${subject.item_ref}.` : ""
    }`;
  }
  return "";
}

// Why this ask exists, why it reached this reader, and who else could end it.
// Every line is read from a persisted fact -- the policy the gate recorded as
// its origin, live role membership, and the request's own approval mode -- so
// the block never guesses at authority it cannot see.
export function appendWhyAsked(context, host, row_) {
  const documentNode = context.document;
  const origin = decisionOrigin(row_);
  const eligibility = decisionEligibility(row_);
  const lines = [
    origin,
    eligibility.you,
    eligibility.others.length
      ? `Also able to decide: ${eligibility.others.join(", ")}.`
      : "",
    eligibility.settles,
  ].filter(Boolean);
  if (!lines.length) return null;
  const asked = el(documentNode, "div", "gate-why");
  asked.appendChild(el(documentNode, "span", "gate-what-label", "Why asked"));
  for (const line of lines) {
    asked.appendChild(el(documentNode, "p", "gate-why-copy", line));
  }
  host.appendChild(asked);
  return asked;
}

// The evidence behind an undetermined verdict, shown rather than counted.
export function appendEvidence(context, host, facts) {
  const documentNode = context.document;
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
  const evidence = block(
    documentNode,
    host,
    "gate-evidence",
    `Evidence · ${artifacts.length} artifact${artifacts.length === 1 ? "" : "s"}`,
  );
  const grid = el(documentNode, "div", "gate-evidence-grid");
  for (const artifact of artifacts) {
    grid.appendChild(
      artifactEvidenceCard(context, artifact, facts.requirement_id),
    );
  }
  evidence.appendChild(grid);
  return evidence;
}

export function appendRelatedEvidence(context, host, facts, subject) {
  const documentNode = context.document;
  const evidence = facts.evidence;
  if (!evidence) {
    host.appendChild(el(
      documentNode, "div", "gate-evidence-state",
      `Related ${subject} screenshot evidence was not recorded on this request.`,
    ));
    return;
  }
  const screenshots = Array.isArray(evidence.screenshots)
    ? evidence.screenshots : [];
  const messages = {
    absent: `No ${subject}-attached QA evidence is recorded.`,
    missing: `Related ${subject} QA runs attached no screenshots.`,
    unavailable: "Screenshot evidence is unavailable on this installation.",
    failed: "Related screenshot evidence includes a failed QA result.",
    stale: "These screenshots cover an older revision than this decision.",
    revision_unknown: "The screenshot revision was not recorded.",
  };
  if (messages[evidence.state]) {
    host.appendChild(el(
      documentNode, "div", `gate-evidence-state is-${evidence.state}`,
      messages[evidence.state],
    ));
  }
  if (!screenshots.length) return;
  const wrap = block(
    documentNode, host, "gate-evidence",
    `Screenshots · ${screenshots.length}`,
  );
  const grid = el(documentNode, "div", "gate-evidence-grid");
  for (const artifact of screenshots) {
    grid.appendChild(artifactEvidenceCard(context, artifact));
  }
  wrap.appendChild(grid);
}

// Exactly what the evidence is evidence OF. A screenshot with no subject,
// run and revision beside it is a picture of some build: the reviewer cannot
// tell which item it came from or whether it is still current.
function appendQaSubject(documentNode, host, facts) {
  const subject = facts.subject || {};
  const checked = block(documentNode, host, "gate-block", "What was checked");
  if (subject.kind === "deployment_run" && subject.deployment_run_id) {
    row(
      documentNode,
      checked,
      String(subject.deployment_run_id),
      subject.target_environment
        ? `released to ${subject.target_environment}`
        : "",
    );
  } else if (subject.item_ref) {
    row(
      documentNode,
      checked,
      String(subject.item_ref),
      String(subject.item_title || ""),
    );
  }
  row(documentNode, checked, `run ${facts.run_id}`, subject.qa_phase || "");
  row(
    documentNode,
    checked,
    facts.code_revision
      ? String(facts.code_revision).slice(0, 12)
      : "revision not recorded",
    facts.code_revision
      ? "revision under test"
      : "this run recorded no code identity",
  );
  return checked;
}

function appendQaBody(context, host, facts) {
  const documentNode = context.document;
  appendQaSubject(documentNode, host, facts);
  if (facts.expected_outcome) {
    const expected = block(
      documentNode, host, "gate-block", "Expected outcome",
    );
    expected.appendChild(el(
      documentNode, "div", "gate-block-copy", String(facts.expected_outcome),
    ));
  }
  if (facts.verdict_reason) {
    const reason = block(
      documentNode, host, "gate-block", "Why the agent could not decide",
    );
    reason.appendChild(el(
      documentNode, "q", "gate-verdict-reason", String(facts.verdict_reason),
    ));
  }
}

function appendLifecycleBody(context, host, facts) {
  const documentNode = context.document;
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

// Machine approvals draw no body here on purpose: what an approver needs
// beside that decision — the machine, its one-time code, who asked — is the
// Machines page the row already links to, and the subtitle carries it.
const BODY_BUILDERS = {
  qa_needs_review: appendQaBody,
  lifecycle_transition_approval: appendLifecycleBody,
  deployment_stage_approval: appendDeploymentBody,
};

export function appendGateBody(context, wrap, row_) {
  const documentNode = context.document;
  const builder = BODY_BUILDERS[row_.kind];
  const prose = approvalProse(row_);
  const summary = decisionSummary(row_);
  if (!builder && !prose && !summary) return null;
  const host = el(documentNode, "div", "gate-body");
  if (summary) host.appendChild(el(
    documentNode, "p", "gate-summary", summary,
  ));
  const facts = row_.subject_context || {};
  if (row_.kind === "qa_needs_review") appendEvidence(context, host, facts);
  else if (row_.kind === "lifecycle_transition_approval") {
    appendRelatedEvidence(context, host, facts, "item");
  } else if (row_.kind === "deployment_stage_approval") {
    appendRelatedEvidence(context, host, facts, "run");
  }
  const details = el(documentNode, "details", "gate-details");
  details.appendChild(el(documentNode, "summary", null, "Details"));
  appendWhyAsked(context, details, row_);
  if (prose) {
    const what = el(documentNode, "div", "gate-what");
    what.appendChild(el(
      documentNode, "span", "gate-what-label", "What you are approving",
    ));
    what.appendChild(el(documentNode, "span", "gate-what-copy", prose));
    details.appendChild(what);
  }
  if (builder) builder(context, details, facts, row_.project_id);
  host.appendChild(details);
  wrap.appendChild(host);
  return host;
}

export const decisionGateBody = {
  appendEvidence,
  appendGateBody,
  appendRelatedEvidence,
  appendWhyAsked,
  approvalProse,
};
