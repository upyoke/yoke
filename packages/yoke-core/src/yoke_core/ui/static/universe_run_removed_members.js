// Removal changes release custody, not the code in the candidate. Keep the
// cancelled QA separate from evidence the carried members still owe.
import { appendCarriedItemHeading } from "./universe_carried_item_titles.js";
import { deploymentRunHref } from "./universe_navigation.js";
import { el } from "./universe_view_support.js";

export function carriedRunItems(row) {
  const removed = new Set((row.removed_member_items || []).map((item) => String(item.public_ref ?? item.ref ?? item.item_ref)));
  const items = (row.member_items || []).length
    ? row.member_items : [
      ...(row.carried_work?.items || []),
      ...(row.carried_work?.bound_projects || []).flatMap((project) =>
        (project.items || []).map((item) => ({
          ...item, project_id: item.project_id ?? project.project_id,
        }))),
    ];
  return items.filter((item) => !removed.has(String(item.public_ref ?? item.ref ?? item.item_ref)));
}

export function appendRemovedMembers(context, host, row, projectId) {
  const items = row.removed_member_items || [];
  if (!items.length) return;
  const documentNode = context.document;
  const batch = el(documentNode, "div", "release-batch release-removed");
  batch.appendChild(el(documentNode, "span", "release-batch-title",
    `Removed · ${items.length} item${items.length === 1 ? "" : "s"}`));
  for (const item of items) {
    const member = el(documentNode, "div", "release-removed-item");
    appendCarriedItemHeading(documentNode, member, item, projectId);
    const note = el(documentNode, "span", "release-removed-note", "QA cancelled — rides ");
    if (item.later_run_id) {
      const link = el(documentNode, "a", "overview-card-link", item.later_run_id);
      link.href = deploymentRunHref(projectId, item.later_run_id);
      note.appendChild(link);
    } else {
      note.appendChild(documentNode.createTextNode("a later release"));
    }
    member.appendChild(note);
    batch.appendChild(member);
  }
  host.appendChild(batch);
}
