import { callFunction } from "./universe_view_support.js";

// A tab-local draft belongs to the signed-in actor and the mounted universe.
// Storage may be unavailable in embedded/private browsers; the form still works.
export async function itemDraftStorage(context) {
  const windowNode = context.document.defaultView;
  let storage;
  try { storage = windowNode?.sessionStorage; } catch { return null; }
  const location = windowNode?.location;
  if (!storage || !location?.origin || !location?.pathname) return null;
  try {
    const [profile, organization] = await Promise.all([
      callFunction(context.client, "profile.get", {}),
      callFunction(context.client, "organizations.get", {}),
    ]);
    const actor = profile.envelope?.result?.actor?.id;
    if (profile.status !== 200 || !profile.envelope.success || actor == null) return null;
    const universe = organization.envelope?.result?.slug;
    if (organization.status !== 200 || !organization.envelope.success || !universe) return null;
    const key = `yoke:item-draft:${JSON.stringify([location.origin, location.pathname, universe, actor])}`;
    return {
      read(projects, initialProjectId) {
        try {
          const saved = JSON.parse(storage.getItem(key) || "null");
          if (!saved || !projects.some((row) => String(row.id) === saved.projectId)) return null;
          if (initialProjectId && String(initialProjectId) !== saved.projectId) return null;
          if (typeof saved.title !== "string" || typeof saved.instruction !== "string") return null;
          return {
            projectId: saved.projectId,
            title: saved.title,
            instruction: saved.instruction,
            workflowId: typeof saved.workflowId === "string" ? saved.workflowId : null,
            posture: saved.posture && typeof saved.posture === "object" ? saved.posture : null,
          };
        } catch { return null; }
      },
      save(projectId, draft) {
        try {
          storage.setItem(key, JSON.stringify({
            projectId: String(projectId),
            title: draft.titleControl?.value ?? draft.title ?? "",
            instruction: draft.instructionControl?.value ?? draft.instruction ?? "",
            workflowId: draft.workflowId,
            posture: draft.posture,
          }));
          return true;
        } catch { return false; }
      },
      clear() { try { storage.removeItem(key); } catch { /* Keep the form usable. */ } },
    };
  } catch { return null; }
}
