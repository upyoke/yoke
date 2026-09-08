import { sessionControlCall } from "./universe_session_control_data.js";

function compareMessages(left, right) {
  const leftTime = String(left.created_at || "");
  const rightTime = String(right.created_at || "");
  if (leftTime !== rightTime) return leftTime < rightTime ? 1 : -1;
  const leftId = String(left.message_id || "");
  const rightId = String(right.message_id || "");
  if (leftId === rightId) return 0;
  return leftId < rightId ? 1 : -1;
}

function merged(existing, added) {
  const rows = new Map(existing.map((row) => [String(row.message_id), row]));
  for (const row of added) rows.set(String(row.message_id), row);
  return [...rows.values()].sort(compareMessages);
}

/** Load every actionable message and cursor-page only settled history. */
export function sessionMessagePageLoader(context, projects, onChange) {
  let actionable = [];
  let settled = [];
  let actionableCount = 0;
  let settledMatchedCount = 0;
  let nextCursor = null;
  let generation = 0;
  let loading = false;
  let failure = null;
  let failedAppend = false;

  const emit = () => { if (context.isMounted()) onChange(); };
  const requestPage = () => sessionControlCall(
    context,
    "session_control.message.list",
    {
      ...(projects === null ? {} : { projects }),
      ...(nextCursor ? { cursor: nextCursor } : {}),
    },
  );

  const load = async (append) => {
    if (!append) {
      generation += 1;
      actionable = [];
      settled = [];
      actionableCount = 0;
      settledMatchedCount = 0;
      nextCursor = null;
    }
    const requested = generation;
    loading = true;
    failure = null;
    failedAppend = false;
    emit();
    let page;
    try {
      page = await requestPage();
    } catch (error) {
      if (requested !== generation) return false;
      loading = false;
      failure = error;
      failedAppend = append;
      emit();
      return false;
    }
    if (requested !== generation) return false;
    loading = false;
    const rows = page.messages || [];
    actionable = merged(
      actionable,
      rows.filter((row) => row.needs_attention),
    );
    settled = merged(
      settled,
      rows.filter((row) => !row.needs_attention),
    );
    if (!append) {
      actionableCount = Number(page.actionable_count) || 0;
      settledMatchedCount = Number(page.settled_matched_count) || 0;
    }
    nextCursor = page.next_cursor || null;
    emit();
    return true;
  };

  return {
    reload: () => load(false),
    loadMore: () => load(true),
    retry: () => load(failedAppend),
    actionable: () => actionable,
    settled: () => settled,
    actionableCount: () => actionableCount,
    settledMatchedCount: () => settledMatchedCount,
    hasMore: () => Boolean(nextCursor),
    loading: () => loading,
    failure: () => failure,
    destroy() { generation += 1; },
  };
}
