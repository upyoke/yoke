// Native disclosure primitives shared by the Overview's strategy and
// frontier bands. The browser owns keyboard interaction and accessibility;
// this module only remembers which disclosures the operator closed when a
// held read repaints or the route is mounted again.

import { el } from "./universe_view_support.js";

const CLOSED_DISCLOSURES = new Set();

export const OVERVIEW_CARD_LIMIT = 8;

function disclosure(
  documentNode,
  { key, title, className, count = null, empty = "Nothing here." },
) {
  const root = el(documentNode, "details", className);
  root.open = !CLOSED_DISCLOSURES.has(key);
  root.setAttribute("data-fold", key);

  const summary = el(documentNode, "summary", `${className}-summary`);
  summary.appendChild(el(documentNode, "span", "overview-fold-chevron"));
  summary.appendChild(el(documentNode, "span", `${className}-title`, title));
  const countNode = el(documentNode, "span", `${className}-count`);
  if (count !== null) countNode.textContent = String(count);
  summary.appendChild(countNode);
  summary.appendChild(el(documentNode, "span", "overview-band-rule"));
  root.appendChild(summary);

  const body = el(documentNode, "div", `${className}-body`);
  root.appendChild(body);
  root.addEventListener("toggle", () => {
    if (root.open) CLOSED_DISCLOSURES.delete(key);
    else CLOSED_DISCLOSURES.add(key);
  });

  root.setCount = (value) => {
    countNode.textContent = value === null || value === undefined
      ? "" : String(value);
  };
  root.renderCards = (cards, message = empty, gridClass = "") => {
    body.replaceChildren();
    if (!cards.length) {
      body.appendChild(el(
        documentNode, "p", "overview-band-empty", message,
      ));
      return;
    }
    const grid = el(
      documentNode,
      "div",
      ["overview-card-grid", gridClass].filter(Boolean).join(" "),
    );
    for (const card of cards) grid.appendChild(card);
    body.appendChild(grid);
  };
  root.renderError = (message) => {
    body.replaceChildren(el(
      documentNode, "p", "error overview-band-error", message,
    ));
  };
  root.body = body;
  return root;
}

export function overviewSection(documentNode, key, title) {
  return disclosure(documentNode, {
    key: `section:${key}`,
    title,
    className: "overview-section",
  });
}

export function overviewBand(documentNode, key, title, empty) {
  const band = disclosure(documentNode, {
    key: `band:${key}`,
    title,
    className: "overview-band",
    empty,
  });
  band.classList.add(`overview-band-${key}`);
  return band;
}

export function rowsInOverviewScope(rows, scope, projects) {
  if (scope === "all") return rows;
  const wanted = new Set();
  for (const projectId of scope || []) {
    wanted.add(String(projectId));
    const project = projects.find(
      (row) => String(row.id) === String(projectId),
    );
    if (project?.slug) wanted.add(String(project.slug));
  }
  return rows.filter((row) => (
    wanted.has(String(row.project_id)) || wanted.has(String(row.project))
  ));
}

// The Active band shows every live-or-stale session in scope. Ready has to
// agree with that exact set — an item one of those sessions holds is already
// in flight — so both bands read the roster through this one predicate.
export function sessionsShownInActive(rows, scope, projects) {
  return rowsInOverviewScope(rows, scope, projects).filter((row) => (
    ["active", "stale"].includes(String(row.liveness || "").toLowerCase())
  ));
}

// The item references those sessions hold live work claims on.
export function itemsClaimedBySessions(sessionRows) {
  const claimed = new Set();
  for (const row of sessionRows) {
    for (const claim of row.claims || []) {
      if (String(claim.target_kind || "") !== "item") continue;
      const ref = String(claim.public_ref || claim.target || "");
      if (ref) claimed.add(ref);
    }
  }
  return claimed;
}

export function successfulResult(callResult) {
  if (callResult?.status === 200 && callResult.envelope?.success) {
    return callResult.envelope.result || {};
  }
  return null;
}

export function callError(callResult, fallback) {
  return callResult?.envelope?.error?.message || fallback;
}

// Test isolation without weakening production persistence: the app never
// invokes this, while DOM tests that deliberately close a section can reset
// module state before mounting their next independent universe.
export function resetOverviewDisclosureState() {
  CLOSED_DISCLOSURES.clear();
}
