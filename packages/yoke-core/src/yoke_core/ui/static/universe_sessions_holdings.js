import { itemDrillInHref } from "./universe_item_routes.js";
import { el, statePill } from "./universe_view_support.js";

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
// claim of theirs covers — one attached row for that item. Only the
// claim entries are holds; the attached row is a worktree lane the
// session watches, or the bare attribution left by filing or updating
// the item, and `work_role` is what tells those two apart.
//
// One hold, one row. Two kinds of claim are deliberately absent, because
// another surface of this same card already states them: steering, which the
// card names once however many projects it covers, and any claim whose
// coordination lease is listed below it — one `work_claims` row that two
// projections both carry. Item claims lead, because they are what an operator
// opens this card to read.
export function holdingEntries(row) {
  const entries = [];
  const leases = Array.isArray(row.coordination_claims)
    ? row.coordination_claims
    : [];
  const leased = new Set(leases.map((lease) => String(lease.lease_key)));
  const claims = (Array.isArray(row.claims) ? row.claims : []).filter(
    (claim) => claim.target_kind !== "steering"
      && !(claim.lease_key && leased.has(String(claim.lease_key))),
  );
  const isItem = (claim) => claim.target_kind === "item";
  for (const claim of [...claims.filter(isItem), ...claims.filter(
    (claim) => !isItem(claim),
  )]) entries.push({ kind: "claim", claim });
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

// What an item is doing right now, beside the link that opens it — the stage
// answers "how far along is this work", and the workflow in front of it says
// which lifecycle those stage names belong to, so `dash` and `blitz` work is
// told apart without opening the item. One pill carries both facts: a fourth
// chip per row would cost this already dense card more than it returns.
function appendStage(documentNode, work, status, workflow) {
  const label = workflow ? `${workflow} · ${status}` : status;
  const stage = statePill(documentNode, status, label);
  if (!stage) return;
  stage.className = `${stage.className} session-item-stage`;
  work.appendChild(stage);
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
  // Every hold names itself: `YOK-2567`, `epic 41 task 3`, `process feed`,
  // `QA_HOST:test-mac`. So the card adds no kind label — one would either
  // repeat the target or, as `item` and `qa_admission` did, put an internal
  // enum in front of an operator. An item claim spends that slot on the
  // stage and workflow the ref cannot say.
  if (claim.target_kind === "item") {
    appendStage(
      documentNode, work, claim.item_status, claim.item_workflow_id,
    );
    const ownsFocus = claim.target === row.current_item;
    if (ownsFocus && row.current_item_title) {
      work.appendChild(el(
        documentNode,
        "span",
        "session-item-title",
        row.current_item_title,
      ));
    }
  }
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
  const laneRole = row.work_role || "";
  const marker = el(documentNode, "span", "session-attached", "↳");
  marker.title = laneRole
    ? "worktree lane on the owning session's item; holds no item claim"
    : "attributed to this session by filing or updating it; "
      + "no claim and no worktree lane on it";
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
  appendStage(
    documentNode, work, row.current_item_status, row.current_item_workflow_id,
  );
  if (row.current_item_title) {
    work.appendChild(el(
      documentNode,
      "span",
      "session-item-title",
      row.current_item_title,
    ));
  }
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
