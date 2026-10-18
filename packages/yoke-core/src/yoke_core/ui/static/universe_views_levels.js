// Settings → Levels renders the engine's model/minimum-effort rows.
import { callFunction, el, renderError, renderTable, section } from "./universe_view_support.js";
import { renderCursorQuotaOrder } from "./quota_pool_order_editor.js";

function levelBlock(documentNode, level, index) {
  const block = el(documentNode, "section", "level");
  block.setAttribute("aria-label", level.name);
  block.setAttribute("data-level", level.name);
  const head = el(documentNode, "div", "level-head");
  head.appendChild(el(documentNode, "span", "level-order", String(index + 1)));
  head.appendChild(el(documentNode, "span", "level-glyph", level.glyph));
  head.appendChild(el(documentNode, "b", "level-name", level.name));
  block.appendChild(head);
  const surfaces = el(documentNode, "div", "level-surfaces");
  surfaces.appendChild(el(documentNode, "span", "level-muted", "Launchable on"));
  for (const surface of level.launchable_surfaces || []) {
    surfaces.appendChild(el(documentNode, "span", "pill good", surface));
  }
  if (!level.launchable_surfaces?.length) surfaces.appendChild(el(documentNode, "span", "pill crit", "No capacity"));
  block.appendChild(surfaces);
  renderTable(block, (level.options || []).map((entry, position) => ({ ...entry, position })), [
    { label: "#", value: (row) => row.position + 1 },
    { label: "MODEL", value: (row) => row.model, mono: true, sub: (row) => row.display_name },
    { label: "MIN EFFORT", value: (row) => row.min_effort },
    { label: "NOW", value: (row) => row.now?.state === "can_launch" ? "Can launch" : "Blocked",
      sub: (row) => row.now?.state === "can_launch" ? null : (row.now?.blockers || []).map((blocker) => blocker.extra ? `${blocker.label} (${blocker.extra})` : blocker.label).join("; ") },
  ], "No models", null, { stack: true, className: "level-options" });
  return block;
}

export async function renderLevelsView(context, main) {
  const documentNode = context.document;
  main.replaceChildren();
  const stack = el(documentNode, "div", "levels");
  const panel = section(documentNode, "Levels");
  stack.appendChild(panel);
  main.appendChild(stack);
  let callResult;
  try {
    callResult = await callFunction(context.client, "universe.level_capacity.get", {});
  } catch (error) {
    callResult = { status: 0, envelope: { success: false, error: { message: String(error) } } };
  }
  if (!context.isMounted()) return;
  if (callResult.status !== 200 || !callResult.envelope.success) {
    panel.renderEnvelope(callResult, renderError);
    return;
  }
  const result = callResult.envelope.result || {};
  if (!Array.isArray(result.cursor_quota_order) || (result.levels || []).some((level) => level.options.some((entry) => !entry.min_effort))) {
    panel.renderEnvelope({ status: 409, envelope: { error: { message: "levels_schema_version_skew: serving build predates minimum-effort Levels. Recovery: ask the control-plane operator to serve the release carrying this contract." } } }, renderError);
    return;
  }
  panel.setCount(result.levels.length);
  panel.renderEnvelope(null, (body) => result.levels.forEach((level, index) => body.appendChild(levelBlock(documentNode, level, index))));
  renderCursorQuotaOrder(context, stack, result.cursor_quota_order, () => renderLevelsView(context, main));
}
