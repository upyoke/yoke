// What a machine is actually carrying, beside what it could carry.
//
// Capacity says whether a machine has room; this says what is using it. Three
// counts an operator reads before staffing — answering, open but quiet, and
// steering — then the seats it hosts with the documents they steer from, then
// the work its sessions hold, named by reference AND title, because a column
// of bare references is a column nobody can choose from.
//
// Held work comes from the sessions' own current holdings, so a machine that
// hosts five sessions shows five sessions' worth of work rather than a number
// derived from its lane count.

import {
  appendMoreDisclosure,
} from "./universe_sessions_holdings_disclosure.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import {
  steeringHoldingText,
  steeringMarker,
} from "./universe_sessions_steering.js";
import { el } from "./universe_view_support.js";

// How many held items a machine lists before it offers the rest.
const WORK_PREVIEW_LIMIT = 2;

function sessionsOnMachine(sessions, relay) {
  return (Array.isArray(sessions) ? sessions : []).filter(
    (row) => row && String(row.machine_id || "") === String(relay.machine_id),
  );
}

function steeringClaims(row) {
  return (row.holdings?.current || []).filter(
    (holding) => String(holding.target_kind || "") === "steering",
  );
}

function heldItems(rows) {
  const held = [];
  for (const row of rows) {
    for (const holding of row.holdings?.current || []) {
      if (String(holding.holding_kind || "") !== "work_claim") continue;
      if (String(holding.target_kind || "") !== "item") continue;
      const reference = String(holding.public_ref || holding.target || "");
      if (!reference) continue;
      held.push({
        reference,
        title: String(holding.item_title || ""),
        projectId: holding.project_id,
        projectSequence: holding.project_sequence,
      });
    }
  }
  return held;
}

function workRow(documentNode, item) {
  const row = el(documentNode, "div", "machine-work-row");
  const href = itemDrillInHref({
    projectId: item.projectId,
    projectSequence: item.projectSequence,
    publicRef: item.reference,
  });
  const reference = el(
    documentNode, href ? "a" : "span", "session-item-link", item.reference,
  );
  if (href) reference.href = href;
  row.appendChild(reference);
  // The title is the half a person chooses from; a column of references is
  // a column nobody can read.
  row.appendChild(el(
    documentNode,
    "span",
    "session-item-title",
    item.title || "title unavailable",
  ));
  return row;
}

export function appendMachineWork(
  documentNode, card, relay, sessions, projects = [],
) {
  const rows = sessionsOnMachine(sessions, relay);
  if (!rows.length) return null;
  const section = el(documentNode, "section", "machine-work");
  const active = rows.filter(
    (row) => String(row.liveness || "").toLowerCase() === "active",
  ).length;
  const steering = rows.filter((row) => steeringClaims(row).length);
  section.appendChild(el(
    documentNode,
    "h3",
    null,
    `${active} active · ${rows.length - active} other open · `
      + `${steering.length} steering`,
  ));
  for (const row of steering) {
    const line = el(documentNode, "div", "machine-steering");
    line.appendChild(steeringMarker(
      documentNode, "session-steering-symbol", { decorative: true },
    ));
    for (const claim of steeringClaims(row)) {
      line.appendChild(el(
        documentNode,
        "span",
        "session-steering-scope",
        steeringHoldingText(claim, projects),
      ));
    }
    section.appendChild(line);
  }
  const items = heldItems(rows);
  if (items.length) {
    const previews = el(documentNode, "div", "machine-work-previews");
    for (const item of items.slice(0, WORK_PREVIEW_LIMIT)) {
      previews.appendChild(workRow(documentNode, item));
    }
    if (items.length > WORK_PREVIEW_LIMIT) {
      const region = el(documentNode, "div", "machine-work-rest");
      region.setAttribute("role", "region");
      region.setAttribute("aria-label", "More held items");
      for (const item of items.slice(WORK_PREVIEW_LIMIT)) {
        region.appendChild(workRow(documentNode, item));
      }
      previews.appendChild(region);
      appendMoreDisclosure(documentNode, previews, {
        key: `machine-work:${relay.machine_id}`,
        hiddenCount: items.length - WORK_PREVIEW_LIMIT,
        region,
        label: "held items",
      });
    }
    section.appendChild(previews);
  }
  card.appendChild(section);
  return section;
}
