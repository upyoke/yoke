import { callFunction } from "./universe_view_support.js";
import { refreshScreenSort } from "./universe_app_shell_support.js";
import { normalizeOuroborosSort } from "./ouroboros_roster_sort.js";

export const OUROBOROS_PAGE_SIZE = 50;

export function createOuroborosLoader({ context, scope, onChange }) {
  const preferences = context.screenPreferences;
  const active = () => !context.signal?.aborted && context.isMounted();
  const criteria = { reviewState: "all", categoryPrefix: "", sort: normalizeOuroborosSort(preferences?.sortFor("ouroboros")) };
  let sequence = 0, rows = [], cursor = null, matchingCount = null;
  let failure = null, loading = false, sortNotice = "", refresh = null, started = false;
  const state = () => ({ criteria: { ...criteria }, rows, matchingCount, loadedCount: rows.length, failure, loading, hasMore: Boolean(cursor), sortNotice });
  const publish = () => { if (active()) onChange(state()); };
  const request = async ({ append = false } = {}) => {
    const token = ++sequence;
    // The shared shell resolves a single project, including old All URLs.
    const project = scope == null ? null : String(scope);
    if (!append) { rows = []; cursor = null; matchingCount = null; }
    loading = true; failure = null; publish();
    let reply;
    try {
      reply = await callFunction(context.client, "ouroboros.entry.list", {
        project, shape: "roster", review_state: criteria.reviewState,
        limit: OUROBOROS_PAGE_SIZE, sort: criteria.sort,
        ...(criteria.categoryPrefix ? { category_prefix: criteria.categoryPrefix } : {}),
        ...(append && cursor ? { cursor } : {}),
      });
    } catch (error) {
      reply = { status: 0, envelope: { success: false, error: { message: String(error) } } };
    }
    if (token !== sequence || !active()) return;
    loading = false;
    if (reply.status !== 200 || !reply.envelope.success) { failure = reply; publish(); return; }
    const result = reply.envelope.result || {};
    const seen = new Set(append ? rows.map(row => row.id) : []);
    const incoming = (result.entries || []).filter(row => !seen.has(row.id));
    rows = append ? [...rows, ...incoming] : incoming;
    cursor = result.next_cursor || null; matchingCount = result.matching_count;
    publish();
  };
  const refreshSort = () => {
    if (!preferences || !active()) return Promise.resolve();
    if (refresh) return refresh;
    refresh = refreshScreenSort(context.client, preferences, "ouroboros").then(notice => {
      if (!active()) return;
      sortNotice = notice;
      const sort = normalizeOuroborosSort(preferences.sortFor("ouroboros"));
      if (sort.column !== criteria.sort.column || sort.direction !== criteria.sort.direction) {
        criteria.sort = sort;
        if (started) return request();
      }
      if (started) publish();
    }).finally(() => { refresh = null; });
    return refresh;
  };
  const onVisible = () => { if (context.document.visibilityState === "visible") refreshSort(); };
  context.document.defaultView?.addEventListener?.("focus", refreshSort);
  context.document.addEventListener?.("visibilitychange", onVisible);
  context.signal?.addEventListener("abort", () => {
    sequence += 1;
    context.document.defaultView?.removeEventListener?.("focus", refreshSort);
    context.document.removeEventListener?.("visibilitychange", onVisible);
  }, { once: true });
  return {
    state,
    start: async () => { await refreshSort(); if (active()) { started = true; return request(); } },
    loadMore: () => cursor ? request({ append: true }) : Promise.resolve(),
    setReviewState: value => { criteria.reviewState = value; return request(); },
    setCategoryPrefix: value => { criteria.categoryPrefix = value; return request(); },
    setSort: column => {
      const direction = criteria.sort.column === column && criteria.sort.direction === "asc" ? "desc" : "asc";
      const chosen = normalizeOuroborosSort({ column, direction });
      criteria.sort = chosen; sortNotice = "";
      preferences?.saveSortFor("ouroboros", chosen).then(notice => {
        if (chosen === criteria.sort && active()) { sortNotice = notice; publish(); }
      });
      return request();
    },
  };
}
