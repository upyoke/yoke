// A person's one org role, changed by an org admin from the Actors roster.

import { callFunction, el } from "./universe_view_support.js";

// `roles` is the roster's person_org_roles; `reload` re-reads the roster once
// actors.role.set lands. A refusal names its reason and restores the select.
export function roleControl(documentNode, actor, roles, roster, feedback, reload) {
  const current = actor.roles?.org?.[0]?.role || "";
  const select = el(documentNode, "select", "actors-role-select");
  select.setAttribute("aria-label", `Org role for ${actor.name}`);
  if (!roles.includes(current)) {
    const none = el(documentNode, "option", null, current || "—");
    none.value = current;
    none.disabled = true;
    select.appendChild(none);
  }
  for (const role of roles) {
    const option = el(documentNode, "option", null, role);
    option.value = role;
    select.appendChild(option);
  }
  select.value = current;
  select.addEventListener("change", async () => {
    const role = select.value;
    select.disabled = true;
    feedback.textContent = `Changing ${actor.name}'s org role to ${role}…`;
    try {
      const changed = await callFunction(roster.client, "actors.role.set", {
        actor_id: actor.id, role,
      });
      if (changed.status === 200 && changed.envelope?.success) {
        await reload();
        return;
      }
      feedback.textContent = changed.envelope?.error?.message || "Role change failed; retry.";
    } catch (error) {
      feedback.textContent = `${error}; retry the change.`;
    }
    select.value = current;
    select.disabled = false;
  });
  return select;
}
