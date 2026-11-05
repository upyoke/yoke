import { callFunction, el } from "./universe_view_support.js";
import { appendRowError } from "./inbox_rows.js";

export function postCard(context, row, reload, projectLabel = null) {
  const doc = context.document;
  const card = el(doc, "article", "review-card inbox-post-card");
  card.setAttribute("data-post-id", String(row.id));
  card.appendChild(el(doc, "h3", "review-title", row.title));
  card.appendChild(el(doc, "p", "review-context", [projectLabel, row.source].filter(Boolean).join(" · ")));
  card.appendChild(el(doc, "p", "inbox-post-body", row.body));
  const fields = el(doc, "dl", "inbox-post-fields");
  for (const [key, value] of Object.entries(row.fields || {})) {
    fields.appendChild(el(doc, "dt", null, key));
    fields.appendChild(el(doc, "dd", null, typeof value === "string" ? value : JSON.stringify(value)));
  }
  card.appendChild(fields);
  const button = el(doc, "button", "item-button primary", "Done");
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const result = await callFunction(context.client, "inbox.posts.done", { post_id: row.id });
      if (result.status !== 200 || !result.envelope.success) {
        throw new Error(result.envelope.error?.message || "The post could not be completed. Reload the Inbox and retry.");
      }
      const post = result.envelope.result?.post || {};
      card.replaceChildren(el(doc, "p", "review-context", `Done by ${post.done_by || "an audience member"} · ${post.done_at || "time unavailable"}`));
      await reload(post);
    } catch (error) {
      button.disabled = false;
      appendRowError(doc, card, String(error));
    }
  });
  card.appendChild(button);
  return card;
}
