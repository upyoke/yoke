import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  loadScopedSection,
  loadSection,
  renderTable,
  scopeBuckets,
  section,
  withProjectColumn,
} from "./universe_view_support.js";

export function renderStrategyView(context, main, scope) {
  const panel = section(context.document, "Strategy");
  main.replaceChildren(panel);
  const projects = context.projects();
  // The strategy read refuses without a project, so "all" fans out into one
  // call per roster project rather than one unfiltered call.
  const buckets = scopeBuckets(scope, projects, true);
  const slugById = new Map(
    projects.map((row) => [String(row.id), row.slug || String(row.id)]),
  );
  loadScopedSection(
    context, panel,
    buckets.map((bucket) => ({
      functionId: "strategy.doc.list",
      payload: {},
      // Strategy docs are project-scoped through the target, not the payload.
      target: { kind: "global", project_id: String(bucket) },
    })),
    (body, callResults) => {
      // The read carries no per-row project, so each row wears the label of
      // the bucket that requested it — never a guess. The bucket id also
      // rides along so a row link can name its project in the route.
      const docs = callResults.flatMap((callResult, index) => (
        ((callResult.envelope.result || {}).docs || []).map((doc) => ({
          ...doc,
          project: slugById.get(buckets[index]) || buckets[index],
          project_id: buckets[index],
        }))
      ));
      // Every bucket served its complete corpus, so the merged length is
      // the fetched total.
      panel.setCount(docs.length);
      renderTable(body, docs, withProjectColumn([
        { label: "slug", value: (doc) => doc.slug },
        { label: "title", value: (doc) => doc.title },
        // The engine resolves the last editor to a label when it knows
        // one; an unattributed doc shows nothing, never a placeholder.
        { label: "owner", value: (doc) => doc.updated_by },
        { label: "last write", value: (doc) => doc.updated_at },
        // Raw bytes exactly as served — the number is the engine's.
        { label: "size", value: (doc) => doc.bytes },
        {
          label: "status", pill: true,
          value: (doc) => (doc.archived ? "archived" : "active"),
        },
      ], scope, (doc) => doc.project), "no strategy docs yet",
      (doc) => buildUniverseRoute("strategy", doc.project_id, doc.slug));
    },
  );
}

// One strategy doc, body included — the drill-in the corpus table opens.
// The doc content is the plan itself, so it renders the same way an item
// body does: served text, monospace, no client-side rewriting.
export function renderStrategyDocDetailView(context, main, projectId, slug) {
  const documentNode = context.document;
  const panel = section(documentNode, slug);
  main.replaceChildren(panel);
  loadSection(
    context, panel,
    "strategy.doc.get",
    { slug: String(slug) },
    (body, callResult) => {
      const doc = callResult.envelope.result || {};
      const summary = el(documentNode, "table", "items kv");
      for (const [label, value] of [
        ["project", doc.project_slug],
        ["last write", doc.updated_at],
        ["status", doc.archived_at ? "archived" : "active"],
      ]) {
        const tr = el(documentNode, "tr");
        tr.appendChild(el(documentNode, "th", null, label));
        tr.appendChild(el(documentNode, "td", null, String(value ?? "")));
        summary.appendChild(tr);
      }
      body.appendChild(summary);
      const content = String(doc.content || "").trim();
      body.appendChild(el(
        documentNode, content ? "pre" : "p",
        content ? "item-body" : "empty",
        content || "no content yet",
      ));
    },
    { kind: "global", project_id: String(projectId) },
  );
}
