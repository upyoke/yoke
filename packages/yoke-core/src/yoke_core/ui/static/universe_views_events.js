import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  loadScopedSection,
  mergedRows,
  scopeBuckets,
  section,
  statePill,
} from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";

const CATEGORY_ORDER = [
  "workflow",
  "sessions",
  "delivery",
  "qa",
  "strategy",
  "access",
  "system",
];

function categoryLabel(category) {
  return category.charAt(0).toUpperCase() + category.slice(1);
}

function targetNode(documentNode, row, projectBySlug) {
  const label = row.target_label || "Universe";
  if (row.target_kind !== "item") return el(documentNode, "span", null, label);
  const project = row.target_project_id ||
    projectBySlug.get(String(row.project || ""));
  if (!project) return el(documentNode, "span", null, label);
  const link = el(documentNode, "a", "row-link", label);
  link.href = buildUniverseRoute(
    "items",
    String(project),
    String(label).replace(/^[A-Za-z]+-/, ""),
  );
  return link;
}

function eventEntry(documentNode, row, projectBySlug) {
  const entry = el(documentNode, "article", "event-entry");
  const when = el(documentNode, "div", "event-time");
  when.appendChild(relativeTime(documentNode, row.created_at));
  entry.appendChild(when);
  entry.appendChild(el(documentNode, "div", "event-rail"));

  const card = el(documentNode, "div", "event-card");
  const header = el(documentNode, "div", "event-header");
  const title = el(documentNode, "div");
  title.appendChild(el(
    documentNode,
    "div",
    "event-name",
    row.event_name || "Event",
  ));
  title.appendChild(el(
    documentNode,
    "div",
    "event-category",
    categoryLabel(row.category || "system"),
  ));
  header.appendChild(title);
  const severity = statePill(
    documentNode,
    row.severity,
    String(row.severity || "").toUpperCase(),
  );
  if (severity) header.appendChild(severity);
  card.appendChild(header);
  if (row.context_label) {
    card.appendChild(el(
      documentNode,
      "p",
      "event-context",
      row.context_label,
    ));
  }
  const meta = el(documentNode, "div", "event-meta");
  const target = el(documentNode, "span");
  target.appendChild(el(documentNode, "strong", null, "Target "));
  target.appendChild(targetNode(documentNode, row, projectBySlug));
  meta.appendChild(target);
  meta.appendChild(el(
    documentNode,
    "span",
    null,
    `Source ${row.source_label || row.source_type || "system"}`,
  ));
  if (row.project) {
    meta.appendChild(el(documentNode, "span", null, `Project ${row.project}`));
  }
  card.appendChild(meta);
  entry.appendChild(card);
  return entry;
}

export function renderEventsView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Events");
  main.replaceChildren(panel);
  const buckets = scopeBuckets(scope, context.projects(), true);
  const projectBySlug = new Map(context.projects().map(
    (row) => [String(row.slug), String(row.id)],
  ));
  loadScopedSection(
    context,
    panel,
    buckets.map((bucket) => ({
      functionId: "events.query.run",
      payload: { project: bucket },
    })),
    (body, callResults) => {
      const rows = mergedRows(callResults, (result) => result.rows);
      const at = (row) => Date.parse(row.created_at) || 0;
      rows.sort((a, b) => at(b) - at(a));
      const counts = new Map();
      for (const row of rows) {
        const category = row.category || "system";
        counts.set(category, (counts.get(category) || 0) + 1);
      }
      let selected = "all";
      const filters = el(documentNode, "div", "event-filter-bar");
      const filterButtons = [];
      const timeline = el(documentNode, "div", "event-timeline");
      const render = () => {
        timeline.replaceChildren();
        for (const [button, category] of filterButtons) {
          const active = category === selected;
          button.classList.toggle("on", active);
          button.setAttribute("aria-pressed", String(active));
        }
        const visible = selected === "all"
          ? rows
          : rows.filter(
            (row) => (row.category || "system") === selected,
          );
        if (!visible.length) {
          timeline.appendChild(el(
            documentNode,
            "p",
            "empty",
            selected === "all"
              ? "no events yet"
              : `no ${selected} events in this window`,
          ));
          return;
        }
        for (const row of visible) {
          timeline.appendChild(eventEntry(documentNode, row, projectBySlug));
        }
      };
      const categories = [
        ["all", `All · ${rows.length}`],
        ...CATEGORY_ORDER.filter((category) => counts.has(category))
          .map((category) => [
            category,
            `${categoryLabel(category)} · ${counts.get(category)}`,
          ]),
      ];
      for (const [category, label] of categories) {
        const button = el(documentNode, "button", "event-filter", label);
        button.type = "button";
        button.setAttribute("data-category", category);
        button.addEventListener("click", () => {
          selected = category;
          render();
        });
        filterButtons.push([button, category]);
        filters.appendChild(button);
      }
      body.appendChild(filters);
      body.appendChild(timeline);
      render();
    },
  );
}
