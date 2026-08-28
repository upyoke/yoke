import { itemDrillInHref } from "./universe_item_routes.js";
import { el, statePill } from "./universe_view_support.js";

function holdingGroups(row) {
  const model = row.holdings || {};
  return {
    current: Array.isArray(model.current) ? model.current : [],
    previous: Array.isArray(model.previous) ? model.previous : [],
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

function appendStage(documentNode, work, status, workflow) {
  const label = workflow ? `${workflow} · ${status}` : status;
  const stage = statePill(documentNode, status, label);
  if (!stage) return;
  stage.className = `${stage.className} session-item-stage`;
  work.appendChild(stage);
}

function titleHolding(entries, row, previous) {
  const items = entries.filter((entry) => entry.target_kind === "item");
  if (!items.length) return null;
  if (previous) return items[0];
  return items.find((entry) => entry.target === row.current_item) || items[0];
}

function holdingMarker(holding) {
  if (holding.holding_kind === "path_claim") {
    return { text: "📁", title: "file claim — this session holds it" };
  }
  if (holding.holding_kind === "strategy_document") {
    return { text: "🛞", title: "strategy-document hold" };
  }
  if (holding.holding_kind === "coordination") {
    return { text: "🔒", title: "coordination lease — shared-operation hold" };
  }
  return { text: "🔒", title: "work claim — this session holds it" };
}

function holdingTarget(holding) {
  if (holding.holding_kind === "coordination" && holding.owner_item_ref) {
    return `${holding.target} (${holding.owner_item_ref})`;
  }
  return String(holding.target || "holding not reported");
}

function appendHoldingEntry(
  documentNode, body, row, holding, { showTitle = false } = {},
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
  target.textContent = holdingTarget(holding);
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
  if (showTitle) {
    const title = holding.item_title
      || (holding.target === row.current_item ? row.current_item_title : "");
    if (title) {
      work.appendChild(el(documentNode, "span", "session-item-title", title));
    }
  }
  body.appendChild(work);
}

function appendAttachedEntry(documentNode, body, row) {
  const work = el(documentNode, "div", "session-work");
  const laneRole = row.work_role || "";
  const marker = el(documentNode, "span", "session-attached", "↳");
  marker.title = laneRole
    ? "worktree lane on the owning session's item; holds no item claim"
    : "attributed to this session by filing or updating it; "
      + "no claim and no worktree lane on it";
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
  appendStage(
    documentNode, work, row.current_item_status, row.current_item_workflow_id,
  );
  if (row.current_item_title) {
    work.appendChild(el(
      documentNode, "span", "session-item-title", row.current_item_title,
    ));
  }
  body.appendChild(work);
}

function appendHoldingGroup(documentNode, body, row, label, entries, previous) {
  const group = el(documentNode, "div", "session-holdings-group");
  group.appendChild(el(
    documentNode, "div", "session-holdings-label", label,
  ));
  const titled = titleHolding(entries, row, previous);
  for (const entry of entries) {
    appendHoldingEntry(documentNode, group, row, entry, {
      showTitle: entry === titled,
    });
  }
  body.appendChild(group);
  return group;
}

export function appendHoldings(documentNode, body, row) {
  const groups = holdingGroups(row);
  let rendered = false;
  if (groups.current.length) {
    appendHoldingGroup(
      documentNode, body, row, "Currently held", groups.current, false,
    );
    rendered = true;
  }
  if (groups.previous.length || groups.previousRemainder) {
    const group = appendHoldingGroup(
      documentNode, body, row, "Previously held", groups.previous, true,
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
  if (
    row.liveness !== "ended" && row.current_item && !ownsFocusedItem(row)
  ) {
    appendAttachedEntry(documentNode, body, row);
    rendered = true;
  }
  if (!rendered && row.liveness !== "ended") {
    const work = el(documentNode, "div", "session-work");
    work.appendChild(el(
      documentNode,
      "span",
      "session-unassigned",
      row.current_item_title || "No actionable work right now",
    ));
    body.appendChild(work);
  }
}
