// Who is holding an item right now, shown on the item's own card.
//
// The compact form answers "is anyone on this, and are they alive" without
// leaving the grid: the harness mark, the executor, and the same status pill
// the roster shows. Revealing it gives the whole session card — the identical
// renderer Sessions uses, so the facts cannot drift between the two screens.
//
// Claim membership is read from the session's live work claims, never from a
// rendered string, and every qualifying claimant gets its own compact card.
// Work claims are exclusive, so a second claimant is an anomaly a reader
// needs to see rather than one the first match should hide.

import {
  attachRevealPanel,
  revealCloseButton,
} from "./universe_reveal_panel.js";
import { appendSessionPrimaryStatus } from "./universe_session_diagnostics.js";
import { harnessIdentity } from "./universe_session_presentation.js";
import { el } from "./universe_view_support.js";

let claimantPanelSequence = 0;

// A session is a qualifying claimant when the roster still calls it live and
// this machine has not seen its process die. Parked does not disqualify it: a
// parked session is waiting by declaration, and its claim is still its own.
export function isQualifyingClaimant(row) {
  const liveness = String(row.liveness || "").toLowerCase();
  if (liveness !== "active" && liveness !== "stale") return false;
  return String(row.native_process?.state || "") !== "gone";
}

export function itemClaimsOf(row) {
  return (row.claims || []).filter(
    (claim) => String(claim.target_kind || "") === "item",
  );
}

export function claimedItemRefs(row) {
  return itemClaimsOf(row)
    .map((claim) => String(claim.public_ref || claim.target || ""))
    .filter(Boolean);
}

// Index the roster by the item each session claims, so a card asks once for
// its own claimants instead of scanning every session per card.
export function claimantsByItemRef(sessionRows) {
  const index = new Map();
  for (const row of sessionRows) {
    for (const ref of claimedItemRefs(row)) {
      if (!index.has(ref)) index.set(ref, []);
      index.get(ref).push(row);
    }
  }
  return index;
}

function miniSessionCard(documentNode, row) {
  const button = el(documentNode, "button", "item-claimant-mini");
  button.type = "button";
  const harness = harnessIdentity(row);
  button.appendChild(el(
    documentNode,
    "span",
    `session-harness ${harness.className}`,
    harness.mark,
  ));
  button.appendChild(el(
    documentNode, "span", "session-executor", harness.label,
  ));
  appendSessionPrimaryStatus(documentNode, button, row);
  return button;
}

/**
 * The claimant control for one session, ready to append to an item card.
 *
 * `renderFullSession` is the Sessions card renderer, passed in rather than
 * imported so this module stays free of the roster view's dependency tree.
 */
export function itemClaimantControl(
  documentNode, row, { renderFullSession, label },
) {
  const host = el(documentNode, "div", "item-claimant reveal-host");
  const trigger = miniSessionCard(documentNode, row);
  trigger.setAttribute("aria-label", label);
  const panel = el(documentNode, "div", "item-claimant-preview");
  claimantPanelSequence += 1;
  panel.id = `item-claimant-preview-${claimantPanelSequence}`;
  const controls = attachRevealPanel({
    documentNode, trigger, panel, container: host,
  });
  panel.appendChild(revealCloseButton(
    documentNode, "Close session ×", controls.close,
  ));
  panel.appendChild(renderFullSession(row));
  host.appendChild(trigger);
  host.appendChild(panel);
  return host;
}

/**
 * Append every qualifying claimant of `reference` to `card`.
 *
 * Returns how many were drawn, so a caller can say "unclaimed" where that is
 * the fact rather than inferring it from an empty element.
 */
export function appendItemClaimants(
  documentNode, card, reference, claimants, renderFullSession,
) {
  const rows = (claimants.get(reference) || []).filter(isQualifyingClaimant);
  if (!rows.length) return 0;
  const host = el(documentNode, "div", "item-claimant-row");
  for (const row of rows) {
    host.appendChild(itemClaimantControl(documentNode, row, {
      renderFullSession,
      label: rows.length > 1
        ? `Show one of ${rows.length} claiming sessions for ${reference}`
        : `Show claiming session for ${reference}`,
    }));
  }
  if (rows.length > 1) {
    host.appendChild(el(
      documentNode,
      "span",
      "item-claimant-conflict",
      `${rows.length} sessions hold this item`,
    ));
  }
  card.appendChild(host);
  return rows.length;
}
