// What a delivered member's QA was, and where its completion stands.
//
// The Shipping card and the item page's Delivery panel both say this, so
// they read one rule. QA disposition is kept apart from completion: a
// recorded no-obligation answer is not a pass, and a waiver is neither.
// Completion reads the done approval's own server-composed ``standing``;
// approval alone never reads as progress, "closing" needs the run's active
// settlement, and an approved item still open says where to read its gates.

export const CLEARED_QA_STATES = new Set(["accepted", "discharged"]);

export function qaDisposition(qa) {
  if (qa.state === "accepted") return "QA passed";
  return qa.no_item_qa_required ? "no item QA required" : "QA waived";
}

// The newest done approval among decision records: for ``itemId`` when a
// run's gates mix members, or every record when they are one item's own.
export function newestDoneApproval(records, itemId = null) {
  return (records || []).filter((record) => (
    record.kind === "lifecycle_transition_approval"
    && (itemId === null || String(record.subject_context?.item_id ?? "") === String(itemId))
    && record.subject_context?.to_stage === "done"
  )).sort((left, right) => Number(right.request_id) - Number(left.request_id))[0] || null;
}

export function completionStanding(approval, { ref, settling }) {
  const gates = `read \`yoke items get ${ref || "the item"} status\` for its done gates`;
  switch (approval?.standing) {
    case "pending":
      return { symbol: "◐", text: "awaiting approval" };
    case "rejected":
      return { symbol: "✗", text: "approval rejected", reason: `The done approval was rejected; ${gates}.` };
    case "approved":
      return settling
        ? { symbol: "◐", text: "approved · closing" }
        : { symbol: "◐", text: "approved · completion pending", reason: `Approved, but its close-out has not completed; ${gates}.` };
    default:
      return { symbol: "◐", text: "awaiting item completion" };
  }
}

// The whole line for a member whose QA is clear: "<disposition> · <completion>".
export function clearedMemberOutcome(qa, approval, options) {
  const completion = completionStanding(approval, options);
  return { ...completion, text: `${qaDisposition(qa)} · ${completion.text}` };
}
