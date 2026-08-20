export function reviewExplanation(review) {
  if (!review) return null;
  const rationale = String(review.rationale || "").trim();
  if (review.state === "awaiting_agent_review") {
    return "Deterministic capture finished. Agent inspection is pending; " +
      "no human decision has been requested.";
  }
  if (review.state === "agent_reviewed") {
    const verdict = String(review.agent_verdict || "recorded");
    return `Agent inspection recorded ${verdict}.` +
      (rationale ? ` Rationale: ${rationale}` : "");
  }
  if (review.state === "agent_undetermined") {
    return "Agent inspection recorded an undetermined verdict, but no " +
      "human decision request is recorded yet." +
      (rationale ? ` Rationale: ${rationale}` : "");
  }
  if (review.state === "human_review_requested") {
    const requestId = review.decision_request?.id;
    return "Agent inspection recorded an undetermined verdict. " +
      `Human decision request ${requestId || ""} is pending in Inbox.` +
      (rationale ? ` Rationale: ${rationale}` : "");
  }
  if (review.state === "human_review_resolved") {
    const action = review.decision_request?.resolution_action || "resolved";
    return `Human review ${action}.` +
      (rationale ? ` Agent rationale: ${rationale}` : "");
  }
  return null;
}
