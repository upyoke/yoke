import { itemDrillInHref } from "./universe_item_routes.js";
import {
  createEventsHistoryLoader,
  SEVERITY_CHOICES,
  SINCE_CHOICES,
} from "./universe_events_history_loader.js";
import {
  el,
  renderError,
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

function targetNode(documentNode, row) {
  const label = row.target_label || "Universe";
  if (row.target_kind !== "item") return el(documentNode, "span", null, label);
  const href = itemDrillInHref({
    projectId: row.target_project_id,
    publicRef: label,
  });
  if (!href) return el(documentNode, "span", null, label);
  const link = el(documentNode, "a", "row-link", label);
  link.href = href;
  return link;
}

function eventEntry(documentNode, row) {
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
  target.appendChild(targetNode(documentNode, row));
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

function selectControl(documentNode, label, choices, onPick) {
  const wrap = el(documentNode, "label", "event-criterion");
  wrap.appendChild(el(documentNode, "span", "event-criterion-label", label));
  const select = documentNode.createElement("select");
  for (const [value, text] of choices) {
    const option = el(documentNode, "option", null, text);
    option.value = value;
    select.appendChild(option);
  }
  select.addEventListener("change", () => onPick(select.value));
  wrap.appendChild(select);
  return wrap;
}

function textControl(documentNode, label, placeholder, onType) {
  const wrap = el(documentNode, "label", "event-criterion");
  wrap.appendChild(el(documentNode, "span", "event-criterion-label", label));
  const input = documentNode.createElement("input");
  input.type = "search";
  input.placeholder = placeholder;
  input.addEventListener("input", () => onType(input.value));
  wrap.appendChild(input);
  return wrap;
}

// The criteria the server pages behind. These narrow the retained history
// itself, unlike the category buttons below, which refine what has loaded.
function criteriaBar(documentNode, loader) {
  const bar = el(documentNode, "div", "event-criteria-bar");
  bar.appendChild(selectControl(
    documentNode,
    "Severity",
    [["", "Any severity"], ...SEVERITY_CHOICES.map(
      (severity) => [severity, `${severity} and above`],
    )],
    (value) => loader.setCriterion("min_severity", value),
  ));
  bar.appendChild(selectControl(
    documentNode,
    "Since",
    SINCE_CHOICES,
    (value) => loader.setCriterion("since", value),
  ));
  bar.appendChild(textControl(
    documentNode,
    "Event",
    "exact event name",
    (value) => loader.setTypedCriterion("event_name", value),
  ));
  bar.appendChild(textControl(
    documentNode,
    "Source",
    "source type",
    (value) => loader.setTypedCriterion("source_type", value),
  ));
  return bar;
}

// Categories count and filter the entries already loaded — never the whole
// retained history, which would cost a query per category per page. The
// labels say so, so a reader never mistakes a loaded count for a total.
function categoryBar(documentNode, rows, onPick) {
  const counts = new Map();
  for (const row of rows) {
    const category = row.category || "system";
    counts.set(category, (counts.get(category) || 0) + 1);
  }
  const bar = el(documentNode, "div", "event-filter-bar");
  bar.appendChild(el(
    documentNode,
    "span",
    "event-filter-scope",
    "Loaded entries:",
  ));
  const choices = [
    ["all", `All · ${rows.length} loaded`],
    ...CATEGORY_ORDER.filter((category) => counts.has(category)).map(
      (category) => [
        category,
        `${categoryLabel(category)} · ${counts.get(category)} loaded`,
      ],
    ),
  ];
  const chips = [];
  for (const [category, label] of choices) {
    const button = el(documentNode, "button", "event-filter", label);
    button.type = "button";
    button.setAttribute("data-category", category);
    button.addEventListener("click", () => onPick(category));
    chips.push([button, category]);
    bar.appendChild(button);
  }
  return { bar, chips };
}

export function renderEventsView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Events");
  let selected = "all";
  let chips = [];
  let timeline = null;
  let loadedRows = [];

  const loader = createEventsHistoryLoader({
    context,
    buckets: scopeBuckets(scope, context.projects(), true),
    onChange: (state) => renderState(state),
  });
  // The criteria controls live outside the panel body, which is replaced on
  // every render: a control that is re-attached mid-render loses the focus
  // and caret of whoever is typing into it.
  main.replaceChildren(criteriaBar(documentNode, loader), panel);

  // Picking a category changes what is shown, not what is loaded, so the
  // chips and the timeline are updated where they stand: replacing them
  // would take the chip the reader just clicked out from under their focus.
  function paintSelection() {
    for (const [button, category] of chips) {
      const active = category === selected;
      button.classList.toggle("on", active);
      button.setAttribute("aria-pressed", String(active));
    }
    if (!timeline) return;
    const visible = selected === "all"
      ? loadedRows
      : loadedRows.filter((row) => (row.category || "system") === selected);
    timeline.replaceChildren();
    if (!visible.length) {
      timeline.appendChild(el(
        documentNode,
        "p",
        "empty",
        selected === "all"
          ? "no events match these filters"
          : `no ${selected} events among the loaded entries`,
      ));
      return;
    }
    for (const row of visible) timeline.appendChild(eventEntry(documentNode, row));
  }

  function renderState(state) {
    if (!context.isMounted()) return;
    // Nothing on screen yet: the failure replaces the timeline and names the
    // way back. A failure with entries already rendered is reported beside
    // them instead — discarding loaded entries because the NEXT page failed
    // is worse than never having asked for it.
    if (state.failure && !state.rows.length) {
      chips = [];
      timeline = null;
      panel.renderEnvelope(state.failure, (body) => {
        renderError(body, state.failure);
        body.appendChild(el(
          documentNode,
          "p",
          "event-recovery",
          "Reload the first page of events, or adjust the filters above.",
        ));
      });
      return;
    }
    loadedRows = state.rows;
    panel.renderEnvelopes([], (body) => {
      if (state.loading && !state.rows.length) {
        chips = [];
        timeline = null;
        body.appendChild(el(documentNode, "p", "empty", "loading…"));
        return;
      }
      const categories = categoryBar(documentNode, state.rows, (category) => {
        selected = category;
        paintSelection();
      });
      chips = categories.chips;
      body.appendChild(categories.bar);
      timeline = el(documentNode, "div", "event-timeline");
      body.appendChild(timeline);
      paintSelection();
      if (!state.hasMore && !state.failure) return;
      const more = el(documentNode, "div", "event-more");
      if (state.failure) {
        renderError(more, state.failure);
        more.appendChild(el(
          documentNode,
          "p",
          "event-recovery",
          "The loaded entries are unchanged. Retry to continue loading.",
        ));
      }
      const button = el(
        documentNode,
        "button",
        "item-button",
        state.loading ? "Loading…" : state.failure ? "Retry" : "Load more",
      );
      button.type = "button";
      button.disabled = state.loading;
      button.addEventListener(
        "click",
        () => (state.failure ? loader.retry() : loader.loadMore()),
      );
      more.appendChild(button);
      body.appendChild(more);
    });
  }

  loader.start();
}
