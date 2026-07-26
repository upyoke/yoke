import {
  el,
  statePill,
} from "./universe_view_support.js";
import {
  formatTimestamp,
  readablePolicyValue,
  workflowPanel,
} from "./workflow_view_primitives.js";

export function actionLink(documentNode, text, href, primary = false) {
  const link = el(
    documentNode,
    "a",
    `item-action${primary ? " primary" : ""}`,
    text,
  );
  link.href = href;
  return link;
}

export function itemHeading(documentNode, item) {
  const header = el(documentNode, "div", "item-detail-heading");
  const copy = el(documentNode, "div", "item-detail-heading-copy");
  copy.appendChild(el(documentNode, "h1", null, item.title));
  const state = el(documentNode, "div", "item-detail-state");
  const pill = statePill(documentNode, item.workflow.stage_label || item.status);
  if (pill) state.appendChild(pill);
  const claim = item.claim;
  if (claim) {
    state.appendChild(el(
      documentNode,
      "span",
      "item-muted",
      `claimed by ${claim.actor_label || claim.session_id}`,
    ));
  } else if (item.owner) {
    state.appendChild(el(
      documentNode,
      "span",
      "item-muted",
      `owned by ${item.owner}`,
    ));
  }
  copy.appendChild(state);
  header.appendChild(copy);
  return header;
}

export function textPanel(documentNode, title, text, emptyText = "None yet.") {
  const { panel, body } = workflowPanel(documentNode, title);
  const clean = String(text || "").trim();
  body.appendChild(el(
    documentNode,
    clean ? "pre" : "p",
    clean ? "item-prose" : "empty",
    clean || emptyText,
  ));
  return panel;
}

export function factsPanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Item details");
  const table = el(documentNode, "table", "items kv item-facts");
  const lane = (item.worktrees || []).find((row) => row.state === "active") ||
    (item.worktrees || [])[0];
  const claim = item.claim;
  const values = [
    ["Project", item.project.name || item.project.slug],
    [
      "Workflow",
      `${item.workflow.name || item.workflow.id} · v${item.workflow.version}`,
    ],
    ["Status", item.workflow.stage_label || item.status],
    ["Owner", item.owner || "unassigned"],
    [
      "Claim",
      claim
        ? `${claim.actor_label || claim.session_id} · ${claim.session_id}`
        : "none",
    ],
    ["Worktree", lane ? lane.branch : "none"],
    ["Created", formatTimestamp(item.created_at)],
  ];
  for (const [label, value] of values) {
    const row = el(documentNode, "tr");
    row.appendChild(el(documentNode, "th", null, label));
    row.appendChild(el(documentNode, "td", null, String(value || "")));
    table.appendChild(row);
  }
  body.appendChild(table);
  return panel;
}

const POSTURE_LABELS = {
  path_claims: "Path claims",
  worktrees: "Worktrees",
  parallelism: "Parallelism",
  generated_children: "Child items",
  delivery: "Delivery",
};

export function posturePanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Execution posture");
  const grid = el(documentNode, "div", "item-posture-grid");
  const policies = item.workflow.policies || {};
  for (const key of [
    "path_claims",
    "worktrees",
    "parallelism",
    "generated_children",
    "delivery",
  ]) {
    const cell = el(documentNode, "div", "item-posture-cell");
    cell.appendChild(el(
      documentNode, "div", "item-posture-label", POSTURE_LABELS[key],
    ));
    cell.appendChild(el(
      documentNode,
      "div",
      "item-posture-value",
      readablePolicyValue(key, policies[key]),
    ));
    grid.appendChild(cell);
  }
  const invariant = el(documentNode, "div", "item-posture-cell locked");
  invariant.appendChild(el(
    documentNode, "div", "item-posture-label", "Database changes",
  ));
  invariant.appendChild(el(
    documentNode, "div", "item-posture-value", "governed · never tunable",
  ));
  grid.appendChild(invariant);
  body.appendChild(grid);
  return panel;
}

function qaOutcome(row) {
  if (row.waived_at) return "waived";
  return row.verdict || row.execution_status || "queued";
}

export function verificationPanel(documentNode, item) {
  const rows = item.qa_requirements || [];
  const { panel, body } = workflowPanel(
    documentNode,
    "Verification",
    { count: rows.length },
  );
  body.className += " item-stack";
  if (!rows.length) {
    body.appendChild(el(
      documentNode,
      "p",
      "empty",
      "No item-scoped verification requirements are materialized.",
    ));
    return panel;
  }
  for (const row of rows) {
    const card = el(documentNode, "div", "item-proof-row");
    const copy = el(documentNode, "div", "item-proof-copy");
    copy.appendChild(el(
      documentNode,
      "div",
      "item-proof-title",
      row.requirement_source || row.qa_kind || `requirement ${row.id}`,
    ));
    copy.appendChild(el(
      documentNode,
      "div",
      "item-proof-subtitle",
      [
        row.qa_kind,
        row.qa_phase,
        row.blocking_mode,
      ].filter(Boolean).join(" · "),
    ));
    card.appendChild(copy);
    const pill = statePill(documentNode, qaOutcome(row));
    if (pill) card.appendChild(pill);
    body.appendChild(card);
  }
  const outcomes = rows.map(qaOutcome);
  const unsatisfied = outcomes.filter(
    (value) => !["pass", "passed", "waived", "succeeded"].includes(
      String(value).toLowerCase(),
    ),
  ).length;
  const union = el(documentNode, "div", "item-proof-union");
  union.appendChild(el(
    documentNode,
    "strong",
    null,
    unsatisfied ? "Union verdict · not satisfied" : "Union verdict · satisfied",
  ));
  union.appendChild(el(
    documentNode,
    "span",
    "item-muted",
    `${rows.length - unsatisfied} satisfied · ${unsatisfied} outstanding`,
  ));
  body.appendChild(union);
  return panel;
}

export function commandPanel(documentNode, item) {
  const { panel, body } = workflowPanel(documentNode, "Run in a harness");
  body.appendChild(el(
    documentNode,
    "p",
    "item-muted",
    "From your yoke-installed project repo:",
  ));
  const executor = item.workflow.next_executor_id ||
    item.workflow.executor_id ||
    item.workflow.id;
  body.appendChild(el(
    documentNode,
    "code",
    "item-command",
    `/yoke ${executor} ${item.public_ref}`,
  ));
  return panel;
}

export function progressPanel(documentNode, item) {
  const log = item.progress_log;
  return textPanel(
    documentNode,
    "Progress Log",
    log && log.content,
    "No progress entries yet.",
  );
}

export function detailColumns(documentNode, left, right) {
  const grid = el(documentNode, "div", "item-detail-grid");
  const leftColumn = el(documentNode, "div", "item-stack");
  for (const child of left) leftColumn.appendChild(child);
  const rightColumn = el(documentNode, "div", "item-stack");
  for (const child of right) rightColumn.appendChild(child);
  grid.appendChild(leftColumn);
  grid.appendChild(rightColumn);
  return grid;
}

export function markdownSection(text, heading) {
  const lines = String(text || "").split(/\r?\n/);
  const target = String(heading).toLowerCase();
  let collecting = false;
  const output = [];
  for (const line of lines) {
    const match = line.match(/^#{2,3}\s+(.+?)\s*$/);
    if (match) {
      const name = match[1].trim().toLowerCase();
      if (collecting && name !== target) break;
      collecting = name === target;
      continue;
    }
    if (collecting) output.push(line);
  }
  return output.join("\n").trim();
}

export function withoutMarkdownSections(text, headings) {
  const omitted = new Set(headings.map((heading) => heading.toLowerCase()));
  const lines = String(text || "").split(/\r?\n/);
  const output = [];
  let skipping = false;
  for (const line of lines) {
    const match = line.match(/^#{2,3}\s+(.+?)\s*$/);
    if (match) {
      skipping = omitted.has(match[1].trim().toLowerCase());
    }
    if (!skipping) output.push(line);
  }
  return output.join("\n").trim();
}
