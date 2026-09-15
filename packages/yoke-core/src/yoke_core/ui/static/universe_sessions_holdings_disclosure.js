import { el } from "./universe_view_support.js";

// Display budgets applied after authority filtering, steering/document
// folding, and same-project document compaction — never as a projection
// truncation of distinct holdings.
export const CURRENT_HOLDINGS_LIMIT = 8;
export const PREVIOUS_HOLDINGS_LIMIT = 3;

const expanded = new Set();
let focusedKey = "";

export function holdingsDisclosureKey(sessionId, section) {
  return `${sessionId}\0${section}`;
}

export function isHoldingsExpanded(sessionId, section) {
  return expanded.has(holdingsDisclosureKey(sessionId, section));
}

function setHidden(node, hide) {
  node.hidden = hide;
  if (hide) node.setAttribute("hidden", "");
  else node.removeAttribute("hidden");
}

function regionId(sessionId, section) {
  return `session-holdings-${String(sessionId).replace(/[^A-Za-z0-9_-]/g, "")}-${
    String(section).replace(/[^A-Za-z0-9_-]/g, "-")
  }`;
}

function projectLabel(projects, projectId) {
  const found = (Array.isArray(projects) ? projects : []).find(
    (row) => String(row.id) === String(projectId),
  );
  return String(found?.slug || found?.name || "").trim() || "unknown project";
}

export function compactStrategyDocuments(entries, projects = []) {
  const units = [];
  const groups = new Map();
  for (const entry of (Array.isArray(entries) ? entries : [])) {
    if (entry?.holding_kind === "strategy_document") {
      const projectId = String(entry.project_id ?? "");
      let group = groups.get(projectId);
      if (!group) {
        group = {
          kind: "documents",
          projectId,
          project: projectLabel(projects, projectId),
          entries: [],
        };
        groups.set(projectId, group);
        units.push(group);
      }
      group.entries.push(entry);
      continue;
    }
    units.push({ kind: "row", entry });
  }
  return units.map((unit) => (
    unit.kind === "documents" && unit.entries.length === 1
      ? { kind: "row", entry: unit.entries[0] }
      : unit
  ));
}

export function pinTitledHolding(units, titled) {
  if (!titled) return units;
  const match = [];
  const rest = [];
  for (const unit of units) {
    if (unit.kind === "row" && unit.entry === titled) match.push(unit);
    else rest.push(unit);
  }
  return [...match, ...rest];
}

export function holdingsMoreLabel(hiddenCount, open) {
  if (open) return "Show less";
  return hiddenCount === 1 ? "and 1 more" : `and ${hiddenCount} more`;
}

export function appendHoldingsMore(
  documentNode, group, { sessionId, section, hiddenCount, region },
) {
  const key = holdingsDisclosureKey(sessionId, section);
  const open = expanded.has(key);
  const id = regionId(sessionId, section);
  region.id = id;
  setHidden(region, !open);
  const button = el(
    documentNode, "button", "session-holdings-more",
    holdingsMoreLabel(hiddenCount, open),
  );
  button.type = "button";
  button.setAttribute("aria-expanded", open ? "true" : "false");
  button.setAttribute("aria-controls", id);
  button.addEventListener("click", () => {
    if (expanded.has(key)) expanded.delete(key);
    else expanded.add(key);
    focusedKey = key;
    const now = expanded.has(key);
    setHidden(region, !now);
    button.setAttribute("aria-expanded", now ? "true" : "false");
    button.textContent = holdingsMoreLabel(hiddenCount, now);
  });
  button.addEventListener("focus", () => { focusedKey = key; });
  group.appendChild(button);
  if (focusedKey === key) button.focus();
  return button;
}

export function appendHoldingsSection(
  documentNode, body, {
    label, previous, entries, sessionId, projects, titled,
    renderRow, renderMarker, attachTooltip,
  },
) {
  const boxed = previous ? "previous" : "current";
  const group = el(
    documentNode, "div", `session-holdings-group session-holdings-${boxed}`,
  );
  group.appendChild(el(documentNode, "div", "session-holdings-label", label));
  const section = boxed;
  const limit = previous ? PREVIOUS_HOLDINGS_LIMIT : CURRENT_HOLDINGS_LIMIT;
  const units = pinTitledHolding(
    compactStrategyDocuments(entries, projects), titled,
  );
  const renderUnit = (parent, unit) => {
    if (unit.kind === "documents") {
      appendCountedDocuments(documentNode, parent, {
        sessionId,
        section: `docs-${section}-${unit.projectId}`,
        project: unit.project,
        entries: unit.entries,
        attachTooltip,
        marker: renderMarker(),
        renderEntry: (region, entry) => renderRow(region, entry, false),
      });
      return;
    }
    renderRow(parent, unit.entry, unit.entry === titled);
  };
  for (const unit of units.slice(0, limit)) renderUnit(group, unit);
  if (units.length > limit) {
    const region = el(documentNode, "div", "session-holdings-rest");
    region.setAttribute("role", "region");
    region.setAttribute("aria-label", label);
    for (const unit of units.slice(limit)) renderUnit(region, unit);
    group.appendChild(region);
    appendHoldingsMore(documentNode, group, {
      sessionId, section, hiddenCount: units.length - limit, region,
    });
  }
  body.appendChild(group);
  return group;
}

export function appendCountedDocuments(
  documentNode, parent, {
    sessionId, section, project, entries, renderEntry, attachTooltip, marker,
  },
) {
  const key = holdingsDisclosureKey(sessionId, section);
  const open = expanded.has(key);
  const id = regionId(sessionId, section);
  const count = entries.length;
  const button = el(documentNode, "button", "session-holdings-docs-toggle");
  button.type = "button";
  button.setAttribute("aria-expanded", open ? "true" : "false");
  button.setAttribute("aria-controls", id);
  button.appendChild(marker);
  attachTooltip(
    documentNode, marker,
    "strategy-document lock — this session holds it",
  );
  button.appendChild(el(
    documentNode, "span", "session-hold-target",
    `${project} · ${count} documents`,
  ));
  const region = el(documentNode, "div", "session-holdings-docs");
  region.id = id;
  region.setAttribute("role", "region");
  region.setAttribute("aria-label", `${project} documents`);
  setHidden(region, !open);
  for (const entry of entries) renderEntry(region, entry);
  button.addEventListener("click", () => {
    if (expanded.has(key)) expanded.delete(key);
    else expanded.add(key);
    focusedKey = key;
    const now = expanded.has(key);
    setHidden(region, !now);
    button.setAttribute("aria-expanded", now ? "true" : "false");
  });
  button.addEventListener("focus", () => { focusedKey = key; });
  parent.appendChild(button);
  parent.appendChild(region);
  if (focusedKey === key) button.focus();
  return button;
}
