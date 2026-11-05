import { callFunction, el } from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
import { appendRowError } from "./inbox_rows.js";

export function postCard(context, row, reload, projectLabel = null) {
  const doc = context.document;
  const card = el(doc, "article", "review-card inbox-post-card");
  card.setAttribute("data-post-id", String(row.id));
  const header = el(doc, "header", "inbox-post-header");
  header.appendChild(el(doc, "h3", "review-title", row.title));
  card.appendChild(header);
  const meta = el(doc, "p", "review-context", [projectLabel, row.source].filter(Boolean).join(" · "));
  if (row.created_at) {
    if (meta.textContent) meta.appendChild(doc.createTextNode(" · "));
    meta.appendChild(relativeTime(doc, row.created_at));
  }
  card.appendChild(meta);
  const values = Object.values(row.fields || {});
  if (row.body?.trim() && !values.some((value) => typeof value === "string" && value.trim() === row.body.trim())) {
    card.appendChild(el(doc, "p", "inbox-post-body", row.body));
  }
  const fields = el(doc, "dl", "inbox-post-fields");
  for (const [key, value] of Object.entries(row.fields || {})) {
    fields.appendChild(el(doc, "dt", null, key));
    const detail = el(doc, "dd");
    const text = typeof value === "string" ? value : JSON.stringify(value);
    const trimmed = typeof value === "string" ? value.trim() : "";
    const email = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed);
    let url = false;
    try { url = ["http:", "https:"].includes(new URL(trimmed).protocol); } catch { /* Plain text. */ }
    if (email || url) {
      const link = el(doc, "a", null, text);
      link.setAttribute("href", email ? `mailto:${trimmed}` : trimmed);
      detail.appendChild(link);
    } else {
      detail.textContent = text;
    }
    fields.appendChild(detail);
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
  header.appendChild(button);
  return card;
}
