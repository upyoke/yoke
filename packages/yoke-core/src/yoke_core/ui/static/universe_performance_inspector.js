import { callFunction, el } from "./universe_view_support.js";
import { durationLabel } from "./universe_performance_chart.js";

export function inspectBucket(context, scopePayload, bucket, trigger) {
  const documentNode = context.document;
  const signal = context.signal;
  const dialog = el(documentNode, "dialog", "performance-inspector");
  const title = el(documentNode, "h2", null, "Contributing calls");
  title.id = "performance-inspector-title";
  dialog.setAttribute("aria-labelledby", title.id);
  const close = el(documentNode, "button", "performance-close", "Close");
  close.type = "button";
  close.addEventListener("click", () => dialog.close());
  const filters = el(documentNode, "div", "performance-series");
  const body = el(documentNode, "div", "performance-contributors");
  const status = el(documentNode, "p", "performance-status");
  status.setAttribute("role", "status");
  dialog.append(title, close, el(documentNode, "p", null,
    `${new Date(bucket.start).toLocaleString()} – ${new Date(bucket.end).toLocaleString()}`), filters, status, body);
  let family = null, sequence = 0;
  const current = () => !signal?.aborted && dialog.open;
  function callRow(row) {
    const card = el(documentNode, "details", "performance-call");
    card.appendChild(el(documentNode, "summary", null,
      `${durationLabel(row.duration_ms)} · ${row.operation} · ${row.outcome || "Unknown outcome"}`));
    card.appendChild(el(documentNode, "p", null,
      `${row.family} · ${row.timing_status} · ${row.wait_reason || "Execution timing"} · ${row.harness || "Unknown harness"} / ${row.surface || "Unknown surface"} · machine ${row.machine || "Unknown"}`));
    if (row.command_summary) card.appendChild(el(documentNode, "pre", null, row.command_summary));
    if (row.span_coverage) card.appendChild(el(documentNode, "p", null, row.span_coverage));
    const dl = el(documentNode, "dl", "performance-breakdown");
    for (const [name, value] of Object.entries(row.breakdown || {})) {
      dl.append(el(documentNode, "dt", null, name.replace(/_ms$/, "").replaceAll("_", " ")),
        el(documentNode, "dd", null, durationLabel(value)));
    }
    for (const name of row.unavailable_spans || []) dl.append(
      el(documentNode, "dt", null, name.replaceAll("_", " ")), el(documentNode, "dd", null, "Unknown · span not recorded here"));
    card.append(dl, el(documentNode, "small", null,
      `Observed ${new Date(row.observed_at).toLocaleString()} · event ${row.event_id} · trace ${row.trace_id || "Unknown"}. Nested timings are not summed.`));
    return card;
  }
  async function load(offset = 0) {
    const token = ++sequence;
    if (offset === 0) body.replaceChildren();
    status.textContent = "Loading contributing observations…";
    try {
      const response = await callFunction(context.client, "events.performance.detail", {
        ...scopePayload, since: bucket.start,
        until: bucket.end, family, offset, limit: 50,
      }, null, { signal });
      if (!current() || token !== sequence) return;
      if (!response.envelope.success) throw new Error(response.envelope.error?.message || "performance_detail_failed: retry inspection");
      const result = response.envelope.result;
      status.textContent = `${result.total} observations · ${result.sampling}. ${result.span_coverage}`;
      result.rows.forEach(row => body.appendChild(callRow(row)));
      if (!result.total) body.appendChild(el(documentNode, "p", null, "Unknown · no retained matching observations"));
      if (result.next_offset !== null) {
        const more = el(documentNode, "button", null, "Load more calls");
        more.type = "button";
        more.addEventListener("click", () => { more.remove(); load(result.next_offset); });
        body.appendChild(more);
      }
    } catch (error) {
      if (current() && token === sequence) status.textContent = `${error.message}. Close and reopen to retry.`;
    }
  }
  for (const [key, label] of [[null, "All"], ["function", "Functions"], ["tool", "Tools"], ["hook", "Hooks"], ["relay", "Relay waits"], ["watcher", "Watchers"]]) {
    const button = el(documentNode, "button", null, label);
    button.type = "button";
    button.addEventListener("click", () => { family = key; load(); });
    filters.appendChild(button);
  }
  dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => { sequence++; dialog.remove(); trigger?.focus(); });
  signal?.addEventListener("abort", () => { sequence++; dialog.close(); dialog.remove(); }, { once: true });
  documentNode.body.appendChild(dialog);
  dialog.showModal();
  close.focus();
  load();
}
