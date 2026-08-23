import { itemDrillInHref } from "./universe_item_routes.js";
import { el } from "./universe_view_support.js";

function claimHref(claim, row) {
  const explicit = itemDrillInHref({
    projectId: claim.item_project_id,
    projectSequence: claim.item_project_sequence,
    publicRef: claim.item_ref || claim.target,
  });
  if (explicit) return explicit;
  if (claim.target_kind === "item" && claim.target === row.current_item) {
    return itemDrillInHref({
      projectId: row.current_item_project_id,
      projectSequence: row.current_item_project_sequence,
      publicRef: row.current_item,
    });
  }
  return null;
}

// One entry per thing the session holds: its work claims, its
// coordination leases, and — when the session's focus names an item no
// claim of theirs covers — the attached worktree lane it is watching.
export function holdingEntries(row) {
  const entries = [];
  const claims = Array.isArray(row.claims) ? row.claims : [];
  const leases = Array.isArray(row.coordination_leases)
    ? row.coordination_leases
    : [];
  for (const claim of claims) entries.push({ kind: "claim", claim });
  for (const lease of leases) entries.push({ kind: "lease", lease });
  const ownsFocus = claims.some(
    (claim) =>
      claim.target_kind === "item" && claim.target === row.current_item,
  );
  if (row.current_item && !ownsFocus) entries.push({ kind: "attached" });
  return entries;
}

export function ownsFocusedItem(row) {
  return (Array.isArray(row.claims) ? row.claims : []).some(
    (claim) =>
      claim.target_kind === "item" && claim.target === row.current_item,
  );
}

function appendClaimEntry(documentNode, body, row, claim) {
  const work = el(documentNode, "div", "session-work");
  const marker = el(documentNode, "span", "session-lock", "🔒");
  marker.title = `this session holds the ${claim.target_kind || "work"} claim`;
  work.appendChild(marker);
  const href = claimHref(claim, row);
  const target = el(
    documentNode,
    href ? "a" : "span",
    href ? "session-item-link" : "session-hold-target",
  );
  target.textContent = String(claim.target);
  if (href) target.href = href;
  work.appendChild(target);
  const ownsFocus =
    claim.target_kind === "item" && claim.target === row.current_item;
  if (ownsFocus && row.current_item_title) {
    work.appendChild(el(
      documentNode,
      "span",
      "session-item-title",
      `· ${row.current_item_title}`,
    ));
  }
  work.appendChild(el(
    documentNode,
    "span",
    "session-work-role",
    ownsFocus ? (row.work_role || "item") : (claim.target_kind || "claim"),
  ));
  body.appendChild(work);
}

function leaseLabel(lease) {
  const key = String(lease.lease_key);
  if (lease.owner_kind === "item" && lease.owner_item_ref) {
    return `${key} (${lease.owner_item_ref})`;
  }
  return key;
}

function appendLeaseEntry(documentNode, body, lease) {
  const work = el(documentNode, "div", "session-work");
  const marker = el(documentNode, "span", "session-lock", "🔒");
  marker.title = "coordination lease — shared-operation hold";
  work.appendChild(marker);
  work.appendChild(el(
    documentNode,
    "span",
    "session-lease-key",
    leaseLabel(lease),
  ));
  body.appendChild(work);
}

function appendAttachedEntry(documentNode, body, row) {
  const work = el(documentNode, "div", "session-work");
  const marker = el(documentNode, "span", "session-lock attached", "↳");
  marker.title =
    "worktree lane on the owning session's item; holds no item claim";
  work.appendChild(marker);
  const href = itemDrillInHref({
    projectId: row.current_item_project_id,
    projectSequence: row.current_item_project_sequence,
    publicRef: row.current_item,
  });
  const item = el(documentNode, href ? "a" : "span", "session-item-link");
  item.textContent = String(row.current_item);
  if (href) item.href = href;
  work.appendChild(item);
  if (row.current_item_title) {
    work.appendChild(el(
      documentNode,
      "span",
      "session-item-title",
      `· ${row.current_item_title}`,
    ));
  }
  work.appendChild(el(
    documentNode,
    "span",
    "session-work-role",
    row.work_role || "attached",
  ));
  body.appendChild(work);
}

export function appendHoldings(documentNode, body, row) {
  const entries = holdingEntries(row);
  if (!entries.length) {
    const work = el(documentNode, "div", "session-work");
    work.appendChild(el(
      documentNode,
      "span",
      "session-unassigned",
      row.current_item_title || "No actionable work right now",
    ));
    body.appendChild(work);
    return;
  }
  for (const entry of entries) {
    if (entry.kind === "claim") {
      appendClaimEntry(documentNode, body, row, entry.claim);
    } else if (entry.kind === "lease") {
      appendLeaseEntry(documentNode, body, entry.lease);
    } else {
      appendAttachedEntry(documentNode, body, row);
    }
  }
}
