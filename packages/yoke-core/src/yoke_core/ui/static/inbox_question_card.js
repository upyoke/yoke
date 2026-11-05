import { el } from "./universe_view_support.js";
import { renderMarkdown } from "./markdown_view.js";

function answerLabel(row) {
  const decision = row.your_decision || row.decisions?.[0] || {};
  const action = row.resolution_action || decision.action;
  const note = row.resolution_note || decision.note || "";
  if (action === "freeform") return note;
  const option = (row.subject_context?.options || []).find((entry) => entry.id === action);
  return `${option?.label || action || "Answer recorded"}${note ? ` · ${note}` : ""}`;
}

export function questionCard(context, row, { onAct, compact = false, projectLabel } = {}) {
  const documentNode = context.document;
  const facts = row.subject_context || {};
  const card = el(documentNode, "article", "review-card inbox-question-card");
  card.setAttribute("data-request-id", String(row.id));
  const subject = facts.item_ref || row.requesting_session_label || row.requesting_session_id || "Session";
  card.appendChild(el(documentNode, "h3", "review-title", `Question · ${subject}`));
  if (projectLabel) card.appendChild(el(documentNode, "p", "review-meta", projectLabel));
  card.appendChild(el(documentNode, "p", "inbox-question-text", facts.question || "Question unavailable"));
  if (facts.context) {
    const disclosure = el(documentNode, "details", "inbox-question-context");
    disclosure.appendChild(el(documentNode, "summary", null, "Context"));
    disclosure.appendChild(renderMarkdown(documentNode, facts.context));
    card.appendChild(disclosure);
  }
  if (compact || row.decided_by_you || row.status === "resolved") {
    card.appendChild(el(documentNode, "p", "inbox-question-answer", `Answer · ${answerLabel(row)}`));
    return card;
  }
  const actions = el(documentNode, "div", "inbox-question-actions");
  for (const option of facts.options || []) {
    if (!(row.actions || []).includes(option.id)) continue;
    const recommended = facts.recommended_option === option.id;
    const button = el(documentNode, "button", "inbox-question-option",
      `${option.label}${recommended ? " (Recommended)" : ""}`);
    button.type = "button";
    if (option.detail) button.title = option.detail;
    button.addEventListener("click", () => onAct(row, option.id, card));
    actions.appendChild(button);
  }
  card.appendChild(actions);
  if ((row.actions || []).includes("freeform")) {
    const label = el(documentNode, "label", "inbox-question-freeform", "Your answer");
    const input = el(documentNode, "textarea", "item-form-control");
    input.maxLength = 4000;
    input.rows = 3;
    label.appendChild(input);
    card.appendChild(label);
    const send = el(documentNode, "button", "inbox-question-send", "Send");
    send.type = "button";
    send.disabled = true;
    input.addEventListener("input", () => { send.disabled = !input.value.trim(); });
    send.addEventListener("click", () => {
      if (input.value.trim()) onAct(row, "freeform", card, input.value.trim());
    });
    card.appendChild(send);
  }
  return card;
}
