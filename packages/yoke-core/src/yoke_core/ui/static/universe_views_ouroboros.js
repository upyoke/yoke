import { renderMarkdown } from "./markdown_view.js";
import { itemDrillInHref } from "./universe_item_routes.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import {
  callFunction,
  el,
  loadSection,
  renderError,
  renderTable,
  scopeBuckets,
  section,
  withProjectColumn,
} from "./universe_view_support.js";
import { actionLink } from "./item_view_primitives.js";

export const OUROBOROS_PAGE_SIZE = 50;

function promotedRef(row) {
  return row.promoted_dash?.public_ref || row.promoted_dash?.item_ref || "";
}

function rosterPayload(bucket, criteria, cursor) {
  return {
    project: bucket,
    shape: "roster",
    review_state: criteria.reviewState,
    limit: OUROBOROS_PAGE_SIZE,
    ...(criteria.categoryPrefix
      ? { category_prefix: criteria.categoryPrefix } : {}),
    ...(cursor ? { cursor } : {}),
  };
}

function failureFrom(callResult) {
  if (callResult.status !== 200 || !callResult.envelope.success) {
    return callResult;
  }
  return null;
}

function mergeBucketPages(pages) {
  const seen = new Set();
  const rows = [];
  for (const page of pages) {
    for (const entry of page.entries || []) {
      if (seen.has(entry.id)) continue;
      seen.add(entry.id);
      rows.push({ ...entry, _bucket: entry._bucket || page.bucket });
    }
  }
  rows.sort((left, right) => right.id - left.id);
  return rows;
}

/**
 * Ouroboros-specific paging: one authorized project bucket per request,
 * keyset continuation per bucket, and a deterministic id-desc merge.
 * Criteria changes start a new sequence; a stale reply is dropped.
 * A failed Load more leaves already-rendered rows in place.
 */
function createOuroborosLoader({ context, scope, onChange }) {
  const criteria = { reviewState: "all", categoryPrefix: "" };
  let sequence = 0;
  let rows = [];
  let cursors = {};
  let matchingCount = null;
  let failure = null;
  let loading = false;

  const state = () => ({
    criteria: { ...criteria },
    rows,
    matchingCount,
    loadedCount: rows.length,
    failure,
    loading,
    hasMore: Object.values(cursors).some(Boolean),
  });
  const publish = () => {
    if (typeof onChange === "function") onChange(state());
  };

  const request = async ({ append }) => {
    sequence += 1;
    const token = sequence;
    const buckets = (() => {
      const raw = scopeBuckets(scope, context.projects(), true);
      if (Array.isArray(raw)) {
        return raw.filter((bucket) => bucket != null).map(String);
      }
      return raw == null ? [] : [String(raw)];
    })();
    const targets = append
      ? buckets.filter((bucket) => cursors[bucket])
      : buckets;
    if (!append) {
      rows = [];
      cursors = {};
      matchingCount = null;
    }
    if (!targets.length) {
      loading = false;
      failure = null;
      publish();
      return;
    }
    loading = true;
    failure = null;
    publish();
    const callResults = await Promise.all(targets.map(async (bucket) => {
      try {
        const callResult = await callFunction(
          context.client,
          "ouroboros.entry.list",
          rosterPayload(bucket, criteria, append ? cursors[bucket] : null),
        );
        return { bucket, callResult };
      } catch (fetchError) {
        return {
          bucket,
          callResult: {
            status: 0,
            envelope: {
              success: false,
              error: { message: String(fetchError) },
            },
          },
        };
      }
    }));
    if (token !== sequence || !context.isMounted()) return;
    loading = false;
    const failed = callResults.find(
      (item) => failureFrom(item.callResult),
    );
    if (failed) {
      failure = failed.callResult;
      publish();
      return;
    }
    const pages = callResults.map((item) => {
      const result = item.callResult.envelope.result || {};
      cursors[item.bucket] = result.next_cursor || null;
      return {
        bucket: item.bucket,
        entries: result.entries || [],
        matching_count: result.matching_count,
      };
    });
    rows = append
      ? mergeBucketPages([{ bucket: null, entries: rows }, ...pages])
      : mergeBucketPages(pages);
    if (!append) {
      matchingCount = pages.reduce(
        (total, page) => total + (
          typeof page.matching_count === "number" ? page.matching_count : 0
        ),
        0,
      );
    }
    publish();
  };

  return {
    state,
    start: () => request({ append: false }),
    loadMore: () => (state().hasMore ? request({ append: true })
      : Promise.resolve()),
    setReviewState: (value) => {
      criteria.reviewState = value;
      return request({ append: false });
    },
    setCategoryPrefix: (value) => {
      criteria.categoryPrefix = value;
      return request({ append: false });
    },
  };
}

function ouroborosFilters(documentNode, loader) {
  const host = el(documentNode, "div", "item-filters");
  const review = el(documentNode, "select", "item-filter-control");
  for (const [value, label] of [
    ["all", "All observations"],
    ["unreviewed", "Unreviewed"],
    ["reviewed", "Reviewed"],
  ]) {
    const option = el(documentNode, "option", null, label);
    option.value = value;
    if (value === "all") option.selected = true;
    review.appendChild(option);
  }
  review.addEventListener("change", () => loader.setReviewState(review.value));
  const prefix = el(documentNode, "input", "item-filter-control");
  prefix.type = "text";
  prefix.placeholder = "Category prefix";
  prefix.addEventListener("change", () => {
    loader.setCategoryPrefix(prefix.value.trim());
  });
  host.appendChild(review);
  host.appendChild(prefix);
  return host;
}

export function renderOuroborosView(context, main, scope) {
  const documentNode = context.document;
  const panel = section(documentNode, "Ouroboros");
  const loaded = el(documentNode, "p", "item-muted ouroboros-loaded-count");
  let loader;
  const renderState = (state) => {
    if (!context.isMounted()) return;
    if (state.failure && !state.rows.length) {
      panel.setCount(null);
      loaded.textContent = "";
      panel.renderEnvelope(state.failure, (body) => {
        renderError(body, state.failure);
        const button = el(documentNode, "button", "item-button", "Retry");
        button.type = "button";
        button.addEventListener("click", () => loader.start());
        body.appendChild(button);
      });
      return;
    }
    panel.setCount(state.matchingCount);
    loaded.textContent = typeof state.matchingCount === "number"
      ? `${state.loadedCount} loaded of ${state.matchingCount} matching`
      : `${state.loadedCount} loaded`;
    panel.renderEnvelopes([], (body) => {
      if (state.loading && !state.rows.length) {
        body.appendChild(el(documentNode, "p", "empty", "loading…"));
        return;
      }
      renderTable(body, state.rows, withProjectColumn([
        { label: "when", value: (row) => row.timestamp },
        { label: "category", value: (row) => row.category, pill: true },
        { label: "agent", value: (row) => row.agent },
        { label: "context", value: (row) => row.context },
        {
          label: "reviewed",
          value: (row) => (row.reviewed_at ? row.reviewed_at : ""),
        },
        {
          label: "promoted work",
          value: (row) => promotedRef(row),
          href: (row) => row.promoted_dash
            ? itemDrillInHref({
              projectId: row.promoted_dash.project_id,
              publicRef: promotedRef(row),
            })
            : null,
        },
      ], scope, (row) => row.project), "nothing noticed yet", (row) => (
        buildUniverseRoute(
          "ouroboros",
          row._bucket || (Array.isArray(scope) ? scope[0] : scope),
          String(row.id),
        )
      ));
      const more = el(documentNode, "div", "item-roster-more");
      if (state.failure) renderError(more, state.failure);
      if (state.hasMore || state.failure) {
        const button = el(
          documentNode,
          "button",
          "item-button",
          state.failure
            ? (state.rows.length ? "Retry load more" : "Retry")
            : (state.loading ? "Loading…" : "Load more"),
        );
        button.type = "button";
        button.disabled = state.loading;
        button.addEventListener("click", () => {
          if (!state.rows.length) loader.start();
          else loader.loadMore();
        });
        more.appendChild(button);
      }
      body.appendChild(more);
    });
  };
  loader = createOuroborosLoader({ context, scope, onChange: renderState });
  main.replaceChildren(ouroborosFilters(documentNode, loader), loaded, panel);
  loader.start();
}

export function renderOuroborosEntryDetailView(
  context,
  main,
  projectId,
  entryId,
  navigation = {},
) {
  const documentNode = context.document;
  const panel = section(documentNode, `Field note #${entryId}`);
  main.replaceChildren(panel);
  loadSection(
    context,
    panel,
    "ouroboros.entry.get",
    { entry_id: Number(entryId), project: String(projectId) },
    (body, callResult) => {
      const entry = (callResult.envelope.result || {}).entry || {};
      if (typeof navigation.setDetailLabel === "function") {
        navigation.setDetailLabel(`Field note #${entry.id || entryId}`);
      }
      const contextLine = [
        entry.category,
        entry.agent ? `noticed by ${entry.agent}` : "",
        entry.context || "",
      ].filter(Boolean).join(" · ");
      body.appendChild(el(
        documentNode, "p", "item-muted", contextLine,
      ));
      body.appendChild(renderMarkdown(documentNode, entry.body, {
        className: "rich-text item-prose",
        emptyText: "No evidence recorded.",
        demoteHeadings: true,
      }));
      if (entry.promoted_dash) {
        const outcome = el(documentNode, "div", "item-detail-state");
        outcome.appendChild(el(
          documentNode, "span", "item-muted", "Promoted to",
        ));
        outcome.appendChild(actionLink(
          documentNode,
          promotedRef(entry),
          itemDrillInHref({
            projectId: entry.promoted_dash.project_id,
            publicRef: promotedRef(entry),
          }),
        ));
        body.appendChild(outcome);
      }
    },
  );
}
