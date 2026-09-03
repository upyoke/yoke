import { itemDrillInHref } from "./universe_item_routes.js";
import {
  STEERING_MARKER_TITLE,
  releasedHoldingHistory,
  steeringDocCovers,
  steeringHoldingText,
  steeringLeadCovers,
} from "./universe_sessions_steering.js";
import { el, statePill } from "./universe_view_support.js";
import { renderStageStrip } from "./universe_stage_strip.js";
import { relativeTime } from "./universe_time.js";

const HOLDING_AUTHORITY_KINDS = new Set([
  "work_claim", "path_claim", "strategy_document", "coordination",
  "worktree_lane",
]);

export function hasHoldingAuthority(holding) {
  return HOLDING_AUTHORITY_KINDS.has(String(holding?.holding_kind || ""));
}

function heldEntries(entries) {
  return (Array.isArray(entries) ? entries : []).filter(hasHoldingAuthority);
}

function holdingGroups(row) {
  const model = row.holdings || {};
  return {
    current: heldEntries(model.current),
    previous: releasedHoldingHistory(heldEntries(model.previous)),
    previousRemainder: Number(model.previous_remainder || 0),
  };
}

function holdingHref(holding, row) {
  const explicit = itemDrillInHref({
    projectId: holding.item_project_id,
    projectSequence: holding.item_project_sequence,
    publicRef: holding.item_ref || holding.target,
  });
  if (explicit) return explicit;
  if (holding.target_kind === "item" && holding.target === row.current_item) {
    return itemDrillInHref({
      projectId: row.current_item_project_id,
      projectSequence: row.current_item_project_sequence,
      publicRef: row.current_item,
    });
  }
  return null;
}

export function ownsFocusedItem(row) {
  return holdingGroups(row).current.some(
    (holding) =>
      holding.target_kind === "item" && holding.target === row.current_item,
  );
}

// The meta line's "claim held" duration follows the top claim the card
// actually renders: the first STEERING lead row when a live seat is up,
// otherwise the first CURRENTLY HELD row, any target_kind.
export function topRenderedClaim(row) {
  const groups = holdingGroups(row);
  const steering = groups.current.filter(
    (holding) => holding.target_kind === "steering",
  );
  if (steering.length) return steering[0];
  const coveredAbove = steeringLeadCovers(row);
  return groups.current.find((holding) => !coveredAbove(holding)) || null;
}

// What puts this session's focused item on its card, if anything. A claim
// is work. A worktree lane on the owning session's item is work too. A
// filing attribution is only work while nobody else has picked the item
// up: once another live session holds the claim, the item is that
// session's, and showing it here points the card at somebody else's work.
export function focusAttribution(row) {
  if (!row.current_item || row.liveness === "ended") return null;
  if (row.owns_current_item || ownsFocusedItem(row)) return "claim";
  if (row.work_role) return "lane";
  // Nobody holds it: this session filed it and it is still sitting there,
  // which is worth saying — under its own label, not in the work position.
  return row.current_item_holder_session_id ? null : "filed";
}

function appendStagePill(documentNode, work, status, workflow) {
  const label = workflow ? `${workflow} · ${status}` : status;
  const stage = statePill(documentNode, status, label);
  if (!stage) return;
  stage.className = `${stage.className} session-item-stage`;
  work.appendChild(stage);
}

function appendStageProgress(documentNode, work, stages) {
  if (!Array.isArray(stages) || !stages.length) return;
  const progress = el(documentNode, "div", "session-item-stage-progress");
  progress.appendChild(renderStageStrip(documentNode, stages));
  work.appendChild(progress);
}

function titleHolding(entries, row) {
  const items = entries.filter((entry) => entry.target_kind === "item");
  if (!items.length) return null;
  return items.find((entry) => entry.target === row.current_item) || items[0];
}

// The marker names WHICH KIND of hold the row is, so one glyph per kind:
// the same glyph everywhere would say only "held", which the box heading
// already says. Ordinary work carries a briefcase; the padlock is reserved
// for a genuine lock — a coordination lease over a shared operation, the
// hold that stops other work from running.
function holdingMarker(holding) {
  if (holding.target_kind === "steering") {
    return { text: "🛞", title: STEERING_MARKER_TITLE };
  }
  if (holding.holding_kind === "path_claim") {
    return { text: "📁", title: "file claim — this session holds it" };
  }
  if (holding.holding_kind === "strategy_document") {
    return {
      text: "📜",
      title: "strategy-document lock — this session holds it",
    };
  }
  if (holding.holding_kind === "coordination") {
    return {
      text: "🔒",
      title: "coordination lease — shared-operation hold",
    };
  }
  if (holding.holding_kind === "worktree_lane") {
    return {
      text: "🌿",
      title: "worktree lane — this session holds the lane",
    };
  }
  return { text: "💼", title: "work claim — this session holds it" };
}

function holdingTarget(holding, projects) {
  if (holding.target_kind === "steering") {
    return steeringHoldingText(holding, projects);
  }
  if (holding.holding_kind === "coordination" && holding.owner_item_ref) {
    return `${holding.target} (${holding.owner_item_ref})`;
  }
  return String(holding.target || "holding not reported");
}

function appendHoldingEntry(
  documentNode, body, row, holding, projects, { showTitle = false } = {},
) {
  const work = el(documentNode, "div", "session-work");
  const markerFacts = holdingMarker(holding);
  const marker = el(documentNode, "span", "session-lock", markerFacts.text);
  marker.title = markerFacts.title;
  work.appendChild(marker);
  const href = holding.target_kind === "item" ? holdingHref(holding, row) : null;
  const target = el(
    documentNode,
    href ? "a" : "span",
    href
      ? "session-item-link"
      : holding.holding_kind === "coordination"
        ? "session-lease-key"
        : "session-hold-target",
  );
  target.textContent = holdingTarget(holding, projects);
  if (href) target.href = href;
  work.appendChild(target);
  if (holding.path_count !== undefined) {
    work.appendChild(el(
      documentNode,
      "span",
      "session-path-count",
      `📁${Number(holding.path_count || 0)}`,
    ));
  }
  const releasedAt = holding.released_at;
  if (releasedAt && !Number.isNaN(Date.parse(String(releasedAt)))) {
    const history = el(documentNode, "span", "session-holding-history", "released ");
    history.appendChild(relativeTime(documentNode, releasedAt));
    const count = Number(holding.occurrence_count || 1);
    if (count > 1) {
      const repeated = el(documentNode, "span", "session-holding-repeat", `×${count}`);
      repeated.title = `held ${count} times`;
      history.appendChild(repeated);
    }
    work.appendChild(history);
  }
  if (showTitle) {
    const title = holding.item_title
      || (holding.target === row.current_item ? row.current_item_title : "");
    if (title) {
      work.appendChild(el(documentNode, "span", "session-item-title", title));
    }
    appendStageProgress(documentNode, work, row.primary_item_stages);
  }
  body.appendChild(work);
}

function appendAttachedEntry(documentNode, body, row, attribution) {
  const work = el(documentNode, "div", "session-work");
  const marker = el(documentNode, "span", "session-attached", "↳");
  marker.title = attribution === "lane"
    ? "worktree lane on the owning session's item; holds no item claim"
    : "filed or updated by this session and unclaimed; "
      + "no session holds a work claim on it";
  work.appendChild(marker);
  const href = itemDrillInHref({
    projectId: row.current_item_project_id,
    projectSequence: row.current_item_project_sequence,
    publicRef: row.current_item,
  });
  const item = el(documentNode, href ? "a" : "span", "session-item-link");
  item.textContent = String(row.current_item);
  if (href) item.href = href;
  work.appendChild(item);
  if (attribution === "filed") {
    appendStagePill(
      documentNode, work, row.current_item_status, row.current_item_workflow_id,
    );
  }
  if (row.current_item_title) {
    work.appendChild(el(
      documentNode, "span", "session-item-title", row.current_item_title,
    ));
  }
  if (attribution === "lane") {
    appendStageProgress(documentNode, work, row.primary_item_stages);
  }
  body.appendChild(work);
}

function holdingsBoxKind(label) {
  if (label === "Currently held") return "current";
  if (label === "Previously held") return "previous";
  return null;
}

function appendHoldingGroup(
  documentNode, body, row, label, entries, previous, projects,
) {
  const boxed = holdingsBoxKind(label);
  const group = el(
    documentNode,
    "div",
    boxed
      ? `session-holdings-group session-holdings-${boxed}`
      : "session-holdings-group",
  );
  group.appendChild(el(
    documentNode, "div", "session-holdings-label", label,
  ));
  const titled = previous ? null : titleHolding(entries, row);
  for (const entry of entries) {
    appendHoldingEntry(documentNode, group, row, entry, projects, {
      showTitle: entry === titled,
    });
  }
  body.appendChild(group);
  return group;
}

// Whether this session holds anything at all. A hold the steering block
// above already states is still a hold, so it counts here even though the
// holdings list leaves it out — the card's duty display is every block on
// it, not this function's output alone.
function holdsAnything(groups) {
  return Boolean(
    groups.current.length || groups.previous.length
      || groups.previousRemainder,
  );
}

export function appendHoldings(documentNode, body, row, projects = []) {
  const groups = holdingGroups(row);
  let rendered = false;
  // The steering block above the holdings already names every seat and
  // document it covers; repeating them here says the same hold twice.
  const coveredAbove = steeringLeadCovers(row);
  const current = groups.current.filter((holding) => !coveredAbove(holding));
  const attribution = focusAttribution(row);
  let currentGroup = null;
  if (current.length) {
    currentGroup = appendHoldingGroup(
      documentNode, body, row, "Currently held", current, false, projects,
    );
    rendered = true;
  }
  if (attribution === "lane") {
    if (!currentGroup) {
      currentGroup = appendHoldingGroup(
        documentNode, body, row, "Currently held", [], false, projects,
      );
    }
    appendAttachedEntry(documentNode, currentGroup, row, attribution);
    rendered = true;
  }
  // A released seat is an ordinary previously-held row (steering marker,
  // same project · docs text as the live lead). Its overlapping document
  // lock folds into that row so the pair is not written twice. A lock no
  // released seat covers keeps its own row. Never nest a Steering box
  // inside Previously held.
  const foldedIntoSeat = steeringDocCovers(groups.previous);
  const previous = groups.previous.filter(
    (holding) => !foldedIntoSeat(holding),
  );
  if (previous.length || groups.previousRemainder) {
    const group = appendHoldingGroup(
      documentNode, body, row, "Previously held", previous, true,
      projects,
    );
    if (groups.previousRemainder) {
      group.appendChild(el(
        documentNode,
        "div",
        "session-holdings-more",
        `and ${groups.previousRemainder} more`,
      ));
    }
    rendered = true;
  }
  if (attribution === "filed") {
    // Its own labelled group, because an unclaimed item this session
    // typed is provenance, not the work the card leads with.
    const group = el(documentNode, "div", "session-holdings-group");
    group.appendChild(el(
      documentNode, "div", "session-holdings-label", "Filed · unclaimed",
    ));
    appendAttachedEntry(documentNode, group, row, attribution);
    body.appendChild(group);
    rendered = true;
  }
  if (!rendered && !holdsAnything(groups) && row.liveness !== "ended") {
    // Boxed like every other work region so an idle card reads as idle
    // rather than as a card whose work region failed to render. No label
    // heading: the line inside already says there is nothing held.
    const group = el(
      documentNode, "div", "session-holdings-group session-holdings-idle",
    );
    const work = el(documentNode, "div", "session-work");
    work.appendChild(el(
      documentNode, "span", "session-unassigned", "No active work claims",
    ));
    group.appendChild(work);
    body.appendChild(group);
  }
}
