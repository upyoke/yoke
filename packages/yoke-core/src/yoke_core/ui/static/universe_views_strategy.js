// Strategy is the corpus itself: standing direction first, then the plans
// executing against it, then the write history under both. Each document is a
// card rather than a table row, because the thing a reader is looking for is
// the authored summary — a column of them is unreadable at table width.

import {
  documentReviewView,
  historyReviewView,
} from "./strategy_view_primitives.js";
import {
  stateActionsPanel,
  strategyReviewCallout,
  strategyStats,
  strategyWriteActivity,
} from "./strategy_view_summary.js";
import {
  isStandingDoc,
  orderStrategyDocs,
  strategyDocumentCard,
} from "./universe_strategy_cards.js";
import { workBand } from "./universe_band_primitives.js";
import { button } from "./workflow_view_primitives.js";
import {
  el,
  loadSection,
  scopeBuckets,
  section,
  settledScopedCalls,
} from "./universe_view_support.js";

export function renderStrategyView(context, main, scope) {
  const documentNode = context.document;
  const statsHost = el(documentNode, "div", "strategy-stats-host");
  const callout = strategyReviewCallout(documentNode);
  const standing = workBand(
    documentNode, "standing", "Standing", "No standing documents.",
  );
  const plans = workBand(
    documentNode, "plans", "Plans", "No plans in this scope.",
  );
  // Archived documents are records, not clutter: the band stays, closed, so
  // nothing that was written is out of reach from the page that holds it.
  const archived = workBand(
    documentNode,
    "archived-docs",
    "Archived",
    "Nothing is archived.",
    { defaultOpen: false },
  );
  // Write history sits under the documents and matches the width their cards
  // actually occupy — stretched to the full page it claimed a precision the
  // 120-day count does not have.
  const writesHost = el(documentNode, "div", "strategy-writes-host");
  main.replaceChildren(
    statsHost, callout, standing, plans, archived, writesHost,
  );

  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, true);
  const projectById = new Map(
    projects.map((row) => [String(row.id), row]),
  );
  settledScopedCalls(
    context,
    buckets.map((bucket) => ({
      functionId: "strategy.surface.list",
      payload: {},
      target: { kind: "global", project_id: String(bucket) },
    })),
  ).then(({ callResults }) => {
    if (!context.isMounted()) return;
    const failure = callResults.find(
      (callResult) => !(callResult.status === 200 && callResult.envelope.success),
    );
    if (failure) {
      const message = failure.envelope?.error?.message
        || "Strategy could not be loaded.";
      for (const band of [standing, plans, archived]) band.renderError(message);
      return;
    }
    const docs = callResults.flatMap((callResult, index) => (
      ((callResult.envelope.result || {}).docs || []).map((doc) => ({
        ...doc,
        project_id: buckets[index],
      }))
    ));
    const writes = callResults.flatMap(
      (callResult) => (callResult.envelope.result || {}).writes || [],
    );
    statsHost.replaceChildren(strategyStats(documentNode, docs));
    const render = (band, rows, isStanding) => {
      const cards = orderStrategyDocs(rows, isStanding).map((doc) => (
        strategyDocumentCard(
          documentNode,
          doc,
          projectById.get(String(doc.project_id)) || { id: doc.project_id },
        )
      ));
      band.setCount(cards.length);
      band.renderCards(
        cards, "No strategy documents in this band.", "strategy-doc-grid",
      );
    };
    const live = docs.filter((doc) => !doc.archived);
    render(standing, live.filter(isStandingDoc), true);
    render(plans, live.filter((doc) => !isStandingDoc(doc)), false);
    render(archived, docs.filter((doc) => doc.archived), false);
    writesHost.replaceChildren(strategyWriteActivity(documentNode, writes));
    matchWritesToCardRow(documentNode, standing, writesHost);
  });
}

// The Writes panel spans the width the document cards above it actually
// occupy. Cards are a responsive grid, so that width is measured rather than
// declared, and re-measured whenever the grid reflows.
function matchWritesToCardRow(documentNode, band, writesHost) {
  const windowNode = documentNode.defaultView;
  const grid = Array.from(band.body.children).find(
    (node) => String(node.className || "").includes("strategy-doc-grid"),
  );
  if (
    !grid
    || typeof windowNode?.ResizeObserver !== "function"
    || typeof grid.getBoundingClientRect !== "function"
  ) return;
  const apply = () => {
    const cards = Array.from(grid.children);
    if (!cards.length) return;
    const left = grid.getBoundingClientRect().left;
    const occupied = Math.max(
      ...cards.map((card) => card.getBoundingClientRect().right - left),
    );
    if (occupied > 0) writesHost.style.width = `${occupied}px`;
  };
  const observer = new windowNode.ResizeObserver(apply);
  observer.observe(grid);
  windowNode.addEventListener(
    "pagehide", () => observer.disconnect(), { once: true },
  );
  apply();
}

function renderDetail(context, main, projectId, doc) {
  const documentNode = context.document;
  let selectedTab = "document";
  const host = el(documentNode, "div", "strategy-detail");
  const heading = el(
    documentNode, "div", "page-head item-detail-heading",
  );
  const headingCopy = el(
    documentNode, "div", "h item-detail-heading-copy",
  );
  headingCopy.appendChild(el(documentNode, "h1", "title", doc.slug));
  heading.appendChild(headingCopy);
  const actions = stateActionsPanel(context, projectId, doc);
  const tabs = el(documentNode, "div", "strategy-tabs");
  tabs.setAttribute("role", "tablist");
  const content = el(documentNode, "div", "strategy-tab-content");
  content.id = "strategy-tab-content";
  content.setAttribute("role", "tabpanel");
  const draw = () => {
    tabs.replaceChildren();
    const definitions = [
      ["document", "Document"],
      ["history", "History"],
    ];
    for (const [index, [id, label]] of definitions.entries()) {
      const tab = button(
        documentNode,
        label,
        `workflow-tab${selectedTab === id ? " selected" : ""}`,
      );
      tab.id = `strategy-tab-${id}`;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(selectedTab === id));
      tab.setAttribute("aria-controls", content.id);
      tab.tabIndex = selectedTab === id ? 0 : -1;
      tab.addEventListener("click", () => {
        selectedTab = id;
        draw();
      });
      tab.addEventListener("keydown", (event) => {
        const delta = event.key === "ArrowRight"
          ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!delta && !["Home", "End"].includes(event.key)) return;
        if (typeof event.preventDefault === "function") event.preventDefault();
        const next = event.key === "Home"
          ? 0
          : event.key === "End"
            ? definitions.length - 1
            : (index + delta + definitions.length) % definitions.length;
        selectedTab = definitions[next][0];
        draw();
        const selected = tabs.children[next];
        if (typeof selected?.focus === "function") selected.focus();
      });
      tabs.appendChild(tab);
    }
    content.setAttribute("aria-labelledby", `strategy-tab-${selectedTab}`);
    content.replaceChildren(
      selectedTab === "history"
        ? historyReviewView(
          context,
          projectId,
          doc,
          () => renderStrategyDocDetailView(
            context, main, projectId, doc.slug,
          ),
        )
        : documentReviewView(documentNode, doc),
    );
  };
  draw();
  host.appendChild(heading);
  host.appendChild(actions);
  host.appendChild(tabs);
  host.appendChild(content);
  main.replaceChildren(host);
}

export function renderStrategyDocDetailView(
  context,
  main,
  projectId,
  slug,
) {
  const loading = section(context.document, String(slug));
  main.replaceChildren(loading);
  loadSection(
    context,
    loading,
    "strategy.surface.get",
    { slug: String(slug) },
    (_body, callResult) => {
      const result = callResult.envelope.result || {};
      renderDetail(context, main, projectId, {
        ...(result.document || {}),
        project_slug: result.project_slug,
      });
    },
    { kind: "global", project_id: String(projectId) },
  );
}
