import { el } from "./universe_view_support.js";
import { renderMarkdown } from "./markdown_view.js";
import { relativeTime } from "./universe_time.js";
import { evidenceStrip } from "./review_evidence_strip.js";

function answerLabel(row) {
  const decision = row.your_decision || row.decisions?.[0] || {};
  const action = row.resolution_action || decision.action;
  if (action === "freeform") return (row.resolution_note || decision.note || "").split("\n")[0];
  return (row.subject_context?.options || []).find((entry) => entry.id === action)?.label || action || "Answer recorded";
}

export function questionCard(context, row, { onAct, compact = false } = {}) {
  const documentNode = context.document;
  const facts = row.subject_context || {};
  const answered = compact || row.decided_by_you || row.status === "resolved";
  const card = el(documentNode, "article", `review-card inbox-question-card${answered ? " compact" : ""}`);
  card.setAttribute("data-request-id", String(row.id));
  if (answered) {
    const line = el(documentNode, "p", "review-effect inbox-question-answer", `Answered: ${answerLabel(row)} · you · `);
    line.appendChild(relativeTime(documentNode, row.resolved_at || row.your_decision?.decided_at));
    card.appendChild(line);
    return card;
  }
  card.appendChild(el(documentNode, "h3", "review-title", facts.question || "Question unavailable"));
  const subject = facts.item_ref || row.requesting_session_label || row.requesting_session_id || "Session";
  const asker = el(documentNode, "p", "review-context", `Asked by ${subject} · `);
  asker.appendChild(relativeTime(documentNode, row.created_at));
  card.appendChild(asker);
  const evidence = evidenceStrip(context, facts.artifacts || []);
  if (evidence) card.appendChild(evidence);
  if (facts.context) {
    const disclosure = el(documentNode, "details", "inbox-question-context");
    disclosure.appendChild(el(documentNode, "summary", null, "Context"));
    disclosure.appendChild(renderMarkdown(documentNode, facts.context));
    card.appendChild(disclosure);
  }
  const options = facts.options || [];
  if (options.length) {
    const actions = el(documentNode, "div", "inbox-question-actions");
    for (const option of options) {
      if (!(row.actions || []).includes(option.id)) continue;
      const recommended = facts.recommended_option === option.id;
      const choice = el(documentNode, "div", "inbox-question-choice");
      const button = el(documentNode, "button", `item-button inbox-question-option${recommended ? " primary" : ""}`, option.label);
      button.type = "button";
      button.addEventListener("click", () => onAct(row, option.id, card));
      choice.appendChild(button);
      if (recommended) choice.appendChild(el(documentNode, "small", "review-context", "Recommended"));
      if (option.detail) choice.appendChild(el(documentNode, "p", "review-context", option.detail));
      actions.appendChild(choice);
    }
    card.appendChild(actions);
  }
  if ((row.actions || []).includes("freeform")) {
    const label = el(documentNode, "label", "inbox-question-freeform", options.length ? "Or write an answer" : "Your answer");
    const input = el(documentNode, "textarea", "item-form-control");
    input.maxLength = 4000;
    input.rows = 3;
    label.appendChild(input);
    card.appendChild(label);
    const send = el(documentNode, "button", "item-button primary inbox-question-send", "Send");
    send.type = "button";
    send.disabled = true;
    const submit = () => { if (!send.disabled && input.value.trim()) onAct(row, "freeform", card, input.value.trim()); };
    input.addEventListener("input", () => {
      send.disabled = !input.value.trim();
      input.style.height = "auto";
      if (input.scrollHeight) input.style.height = `${input.scrollHeight}px`;
    });
    input.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); submit(); }
    });
    send.addEventListener("click", submit);
    card.appendChild(send);
  }
  return card;
}
