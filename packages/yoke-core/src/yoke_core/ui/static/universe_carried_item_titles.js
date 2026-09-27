// A carried item's reference and title, each a link to the item.
//
// A run payload does not always carry its items' titles; an entry with a
// bare reference reads as an item nobody can identify. The titles a payload
// omits are read from each item's own record, once per view.

import { itemDrillInHref } from "./universe_item_routes.js";
import { callFunction, el } from "./universe_view_support.js";

function carriedRef(item) {
  return String(item.ref || item.public_ref || item.item_ref
    || `item ${item.item_id ?? item.id}`);
}

function titleOf(item) {
  return String(item.title || item.item_title || "");
}

function titleKey(item, projectId) {
  return `${item.project_id ?? projectId ?? ""}|${carriedRef(item)}`;
}

// Map of `project|ref` to title for the items whose payload has none.
export async function loadMissingItemTitles(context, items) {
  const titles = new Map();
  const missing = new Map();
  for (const item of items || []) {
    if (titleOf(item) || item.project_id == null) continue;
    const ref = item.ref || item.public_ref || item.item_ref;
    if (ref) missing.set(titleKey(item), { ref: String(ref), project: String(item.project_id) });
  }
  await Promise.all([...missing].map(async ([key, { ref, project }]) => {
    try {
      const read = await callFunction(context.client, "items.detail.get", {},
        { kind: "item", public_ref: ref, project_id: project });
      const title = read.status === 200 && read.envelope.success
        ? read.envelope.result?.item?.title : null;
      if (title) titles.set(key, String(title));
    } catch {
      // A title that cannot be read leaves the reference standing alone.
    }
  }));
  return titles;
}

// `titles` is what `loadMissingItemTitles` returned, when the payload
// omitted a title.
export function appendCarriedItemHeading(documentNode, host, item, projectId, titles) {
  const ref = carriedRef(item);
  const href = itemDrillInHref({
    projectId: item.project_id ?? projectId,
    projectSequence: item.project_sequence,
    publicRef: ref,
  });
  const code = el(documentNode, href ? "a" : "code", "mono carried-item-ref", ref);
  if (href) code.href = href;
  host.appendChild(code);
  const text = titleOf(item) || titles?.get(titleKey(item, projectId)) || "";
  const title = el(documentNode, href && text ? "a" : "span", "carried-item-title", text);
  if (href && text) title.href = href;
  host.appendChild(title);
}

export const universeCarriedItemTitles = {
  appendCarriedItemHeading,
  loadMissingItemTitles,
};
