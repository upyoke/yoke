// The one name a QA case goes by on every page: what ran, against what —
// "Browser inspection · run-20260927-004", "Command check · PLAT-151".
//
// A case key or a bare requirement id tells a reader which row they are on
// and nothing about what it checked. The method says what ran; the item or
// deployment run it answers for says against what. The activity table, the
// case page title and breadcrumb, and any run or item surface that links to a
// case all draw the name here so a reader follows one label across pages.

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
export function qaCaseItemRef(row) {
  return row?.public_ref ?? row?.deployment_member_public_ref ?? null;
}

// The response already names the item by its public ref. Run-only and
// subject-less checks keep their run or requirement label.
export function qaCaseSubject(row, itemRef = null) {
  const ref = String(itemRef || row?.item_ref || qaCaseItemRef(row) || "").trim();
  if (ref) return ref;
  if (row?.deployment_run_id) return String(row.deployment_run_id);
  return row?.requirement_id != null ? `case ${row.requirement_id}` : "";
}

export function qaCaseName(row, itemRef = null) {
  return [qaCaseMethodLabel(row), qaCaseSubject(row, itemRef)]
    .filter(Boolean).join(" · ");
}

// Public refs come from the response, so naming needs no identity lookup.
export async function loadQaCaseItemRefs(_context, rows) {
  return new Map(rows.map((row) => [qaCaseItemRef(row), qaCaseSubject(row)])
    .filter(([ref]) => ref != null));
}

export function qaCaseItemRefLoader() {
  return (row) => Promise.resolve(row?.item_ref || qaCaseItemRef(row));
}
