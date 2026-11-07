// Home membership comes only from the server's frontier_group projection.
// Dependency references are a separate drawing and never alter these lists.
import { claimantsByItemRef } from "./universe_item_claimant.js";
import { sessionIsLive } from "./universe_session_diagnostics.js";

export const reference = (row) => String(row.public_ref || "");
export const enabled = (value) => [true, 1, "1", "true"].includes(value);
export const finishedAt = (row) => row.finished_at || "";
export const homeHref = (row) => row.frontier_group?.section === "waiting"
  ? "#frontier-waiting" : `#frontier-home-${encodeURIComponent(reference(row))}`;

export function waitingReason(row, blockedRows = []) {
  const group = row.frontier_group || {};
  const blockers = [...new Set(blockedRows.map((entry) => entry.blocking_item).filter(Boolean))];
  const text = row.blocked_reason || [...new Set(blockedRows.map((entry) => entry.why).filter(Boolean))].join(" ")
    || row.next_actor?.sentence || "Open the item for the next action.";
  let label = "On hold";
  let tone = "blocked";
  if (enabled(row.frozen)) { label = "Frozen"; tone = "frozen"; }
  else if (enabled(row.blocked)) label = "Blocked";
  else if (group.reason === "needs_spec" || blockedRows.some((entry) => entry.needs_spec)) label = "Needs a spec";
  else if (blockers.length) {
    label = blockers.length === 1 ? `Waiting for ${blockers[0]}` : `Waiting for ${blockers.length} items`;
    tone = "dependency";
  } else if (blockedRows.length) label = "Held";
  else if (group.section === "waiting") { label = "Waiting"; tone = "dependency"; }
  else if (group.section === "in_progress") return null;
  return {
    rank: tone === "dependency" ? 2 : 1,
    landing: group.section === "waiting" && blockedRows.length > 0
      && blockedRows.every((entry) => entry.gate_point && entry.gate_point !== "activation"),
    flag: { label, text, tone },
  };
}

export function frontierBandRows({ items, readyRows, blockedRows, sessionRows }) {
  const readyByRef = new Map(readyRows.map((row) => [reference(row), row]));
  const blockedByRef = new Map();
  for (const row of blockedRows) {
    const ref = reference(row);
    if (!blockedByRef.has(ref)) blockedByRef.set(ref, []);
    blockedByRef.get(ref).push(row);
  }
  const groups = new Set(["waiting", "on_hold", "ready", "in_progress", "release", "done"]);
  if (items.some((row) => !groups.has(row.frontier_group?.section))) {
    throw new Error("frontier_group_unavailable: Update the serving server to the release "
      + "these page assets came from, then reload Frontier.");
  }
  const ordered = [...items].sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  const inSection = (name) => ordered.filter((row) => row.frontier_group.section === name);
  const withReason = (row) => ({ row, reason: waitingReason(row, blockedByRef.get(reference(row))) });
  const sessions = sessionRows.filter(sessionIsLive);
  const stages = new Map(sessions.filter((row) => row.current_item && row.primary_item_stages?.length)
    .map((row) => [row.current_item, row.primary_item_stages]));
  return {
    waiting: inSection("waiting").map(withReason),
    held: inSection("on_hold").map(withReason),
    ready: inSection("ready").map((row) => ({ ...readyByRef.get(reference(row)), ...row })),
    active: inSection("in_progress").map(withReason),
    releasing: inSection("release"),
    done: inSection("done").sort((a, b) => finishedAt(b).localeCompare(finishedAt(a))),
    claimants: claimantsByItemRef(sessions),
    stages,
  };
}
