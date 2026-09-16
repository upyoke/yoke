// What a run is bound to, and what it left behind when it stopped.
//
// A release freezes an identity: the candidate commit it carries, the
// artifact built from it, the moment its membership stopped changing, and
// the target it is going to. Those four facts decide whether evidence
// recorded against this run still answers for it, so they belong on the page
// rather than one truncated commit in the subtitle.
//
// Every value here is a durable column on the run row or the environment it
// names. A fact the record does not hold says so: an unfrozen composition and
// a frozen one are different states, and rendering the first as blank makes
// them look alike.

import { deploymentRunHref } from "./universe_navigation.js";
import { relativeAgePhrase } from "./universe_time.js";
import { callFunction, el } from "./universe_view_support.js";

const TERMINAL_STATUSES = new Set(["cancelled", "stopped", "failed"]);

function factRow(documentNode, host, label, value, { mono = false } = {}) {
  host.appendChild(el(documentNode, "span", "run-fact-label", label));
  const cell = el(documentNode, "span", `run-fact-value${mono ? " mono" : ""}`);
  if (typeof value === "string") cell.textContent = value;
  else cell.appendChild(value);
  host.appendChild(cell);
}

// The environment a persistent target names, read from the project's own
// infrastructure roster. A run-created preview has no registered row, which
// is a different answer from "this project has no environments".
export async function loadRunTarget(context, project, environmentName) {
  if (!project || !environmentName) return null;
  try {
    const read = await callFunction(
      context.client, "projects.infrastructure.list", { project: String(project.id) },
    );
    if (read.status !== 200 || !read.envelope.success) return null;
    const rows = read.envelope.result?.environments || [];
    return rows.find(
      (row) => String(row.name || "").toLowerCase()
        === String(environmentName).toLowerCase(),
    ) || null;
  } catch {
    return null;
  }
}

export function runIdentityCard(context, row, environment) {
  const documentNode = context.document;
  const card = el(documentNode, "section", "run-card run-identity");
  card.appendChild(el(documentNode, "h2", null, "Identity"));
  const facts = el(documentNode, "div", "run-facts");
  factRow(
    documentNode, facts, "Candidate",
    row.release_lineage ? String(row.release_lineage) : "no candidate recorded",
    { mono: Boolean(row.release_lineage) },
  );
  factRow(
    documentNode, facts, "Artifact",
    row.artifact_identity ? String(row.artifact_identity) : "not recorded",
    { mono: Boolean(row.artifact_identity) },
  );
  // Freezing is what makes the member list answerable later: before it, the
  // composition can still change, so evidence against it proves less.
  factRow(
    documentNode, facts, "Members frozen",
    row.composition_frozen_at
      ? relativeAgePhrase(row.composition_frozen_at)
      : "not frozen",
  );
  const targetName = row.target_environment || row.target_tier || "not recorded";
  if (environment?.url) {
    const link = el(documentNode, "a", "run-target-url", String(environment.url));
    link.href = String(environment.url);
    link.rel = "noreferrer";
    const wrap = el(documentNode, "span");
    wrap.appendChild(el(documentNode, "span", "run-target-name", `${targetName} · `));
    wrap.appendChild(link);
    factRow(documentNode, facts, "Target", wrap);
  } else {
    factRow(
      documentNode,
      facts,
      "Target",
      row.target_tier === "persistent" || environment
        ? `${targetName} · no URL recorded`
        : `${targetName} · created by this run`,
    );
  }
  card.appendChild(facts);
  return card;
}

// Every run that carried one of this run's members, newest first. A cancelled
// release does not undo what it deployed and does not hand its evidence to
// whatever replaces it, so the replacement is worth naming — and the reader
// finds it through the work, which is the only durable link between the two.
export async function loadSiblingRuns(context, project, items, runId) {
  // Membership names its item `id`; derived carried work names it `item_id`.
  const memberId = items
    .map((item) => Number(item.item_id ?? item.id))
    .find((id) => Number.isFinite(id) && id > 0);
  if (!memberId || !project) return [];
  try {
    const read = await callFunction(
      context.client,
      "deployment_runs.find_by_item",
      {},
      { kind: "item", item_id: memberId, project_id: String(project.id) },
    );
    if (read.status !== 200 || !read.envelope.success) return [];
    return (read.envelope.result?.rows || [])
      .filter((candidate) => String(candidate.id) !== String(runId))
      .sort((left, right) => String(right.created_at || "")
        .localeCompare(String(left.created_at || "")));
  } catch {
    return [];
  }
}

export function appendRunAftermath(context, card, row, project, siblings) {
  const documentNode = context.document;
  const status = String(row.status || "");
  if (!TERMINAL_STATUSES.has(status)) return;
  card.appendChild(el(
    documentNode,
    "p",
    "run-copy run-aftermath",
    status === "cancelled" || status === "stopped"
      ? "Stopping a release keeps its history and does not undo what it already "
        + "deployed. Its evidence and approvals answer for this candidate only; "
        + "a replacement runs its own checks."
      : "The run stopped. Its evidence answers for this candidate only; a "
        + "replacement runs its own checks.",
  ));
  if (!siblings.length) return;
  const list = el(documentNode, "div", "run-siblings");
  list.appendChild(el(
    documentNode, "span", "overview-run-batch-title", "Other releases carrying this work",
  ));
  for (const sibling of siblings) {
    const entry = el(documentNode, "div", "run-sibling");
    const link = el(documentNode, "a", "mono", String(sibling.id));
    link.href = deploymentRunHref(project?.id, sibling.id);
    entry.appendChild(link);
    entry.appendChild(el(
      documentNode,
      "span",
      null,
      [sibling.status, sibling.current_stage].filter(Boolean).join(" · "),
    ));
    list.appendChild(entry);
  }
  card.appendChild(list);
}
