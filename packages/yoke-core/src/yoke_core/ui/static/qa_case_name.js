// The one name a QA case goes by on every page: what ran, against what —
// "Browser inspection · run-20260927-004", "Command check · PLAT-151".
//
// A case key or a bare requirement id tells a reader which row they are on
// and nothing about what it checked. The method says what ran; the item or
// deployment run it answers for says against what. The activity table, the
// case page title and breadcrumb, and any run or item surface that links to a
// case all draw the name here so a reader follows one label across pages.

import { callFunction } from "./universe_view_support.js";

// A command case runs a registered project command; "Command check" reads as
// the kind of check it is rather than the bare method id.
export function qaCaseMethodLabel(row) {
  const methodId = String(row?.method_id || "").trim().toLowerCase();
  const methodName = String(row?.method_name || "").trim();
  if (methodId === "command" || /^command\b/i.test(methodName)) {
    return "Command check";
  }
  return methodName || String(row?.method_id || row?.qa_kind || "").trim()
    || "Check";
}

// The public item ref a check answers for: its own item, or the carried
// item a release check was run for.
export function qaCaseItemId(row) {
  return row?.public_ref ?? row?.deployment_member_public_ref ?? null;
}

// Against what the case ran. An item is named by its public ref; a check
// with no item answers for its deployment run. A ref the caller could not
// resolve falls back to the id it does have rather than to nothing.
export function qaCaseSubject(row, itemRef = null) {
  const ref = String(itemRef || row?.item_ref || "").trim();
  if (ref) return ref;
  const itemId = qaCaseItemId(row);
  if (row?.deployment_run_id && itemId == null) return String(row.deployment_run_id);
  if (itemId != null) return `item ${itemId}`;
  return row?.requirement_id != null ? `case ${row.requirement_id}` : "";
}

export function qaCaseName(row, itemRef = null) {
  return [qaCaseMethodLabel(row), qaCaseSubject(row, itemRef)]
    .filter(Boolean).join(" · ");
}

// Public refs for the items a set of checks answers for, read once per item.
// A failed read leaves that item out, and its name falls back to the id.
export async function loadQaCaseItemRefs(context, rows) {
  const ids = [...new Set(rows.map(qaCaseItemId).filter((id) => id != null))];
  const refs = new Map();
  await Promise.all(ids.map(async (itemId) => {
    try {
      const result = await callFunction(
        context.client, "items.detail.get", {}, { kind: "item", public_ref: itemId },
      );
      const ref = result.status === 200 && result.envelope.success
        ? result.envelope.result?.item?.public_ref : null;
      if (ref) refs.set(itemId, String(ref));
    } catch {
      // The name keeps the item id; the page still renders.
    }
  }));
  return refs;
}

// One activity mount owns this cache. Paging reuses pending and completed
// lookups without retaining another actor's or universe's item identities.
export function qaCaseItemRefLoader(context) {
  const requests = new Map();
  return (row) => {
    const itemId = qaCaseItemId(row);
    if (row.item_ref || itemId == null) return Promise.resolve(row.item_ref || null);
    if (!requests.has(itemId)) {
      requests.set(itemId, loadQaCaseItemRefs(context, [row])
        .then((refs) => refs.get(itemId)));
    }
    return requests.get(itemId);
  };
}
