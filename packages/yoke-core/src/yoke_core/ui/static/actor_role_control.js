// Human org roles inherit into projects; only owners may edit owners. A
// person may hold no org role and reach only their project grants.

import { callFunction, el } from "./universe_view_support.js";

// `roles` is the roster's person_org_roles; `reload` re-reads the roster once
// actors.role.set or actors.role.remove lands. A refusal names its reason and
// restores the select.
export function callerIsOwner(roster) {
  const caller = roster.rows?.find((row) => row.id === roster.current_actor_id);
  return caller?.status === "active" && caller.kind === "human"
    && caller.roles?.org?.some((grant) => grant.role === "owner");
}

export function actorIsOwner(actor) {
  return actor.roles?.org?.some((grant) => grant.role === "owner")
    || actor.roles?.projects?.some((grant) => grant.role === "owner");
}

export const NO_ORG_ROLE = "none";

export function roleControl(documentNode, actor, roles, roster, feedback, reload) {
  // One role selects it and none selects "No org role"; several left from
  // before the one-role rule show what is held and ask for a choice.
  const held = (actor.roles?.org || []).map((grant) => grant.role);
  const current = held.length === 0 ? NO_ORG_ROLE : held.length === 1 ? held[0] : "";
  const select = el(documentNode, "select", "actors-role-select");
  select.setAttribute("aria-label", `Org role for ${actor.name}`);
  if (current !== NO_ORG_ROLE && !roles.includes(current)) {
    const placeholder = el(documentNode, "option", null, held.join(", ") || "—");
    placeholder.value = "";
    placeholder.disabled = true;
    select.appendChild(placeholder);
  }
  for (const role of roles.filter((role) => role !== "owner" || callerIsOwner(roster))) {
    const option = el(documentNode, "option", null, role);
    option.value = role;
    select.appendChild(option);
  }
  const none = el(documentNode, "option", null, "No org role");
  none.value = NO_ORG_ROLE;
  select.appendChild(none);
  select.value = current;
  select.disabled = actorIsOwner(actor) && !callerIsOwner(roster);
  select.addEventListener("change", async () => {
    const role = select.value;
    const removing = role === NO_ORG_ROLE;
    select.disabled = true;
    feedback.textContent = removing
      ? `Removing ${actor.name}'s org role…` : `Changing ${actor.name}'s org role to ${role}…`;
    try {
      const changed = await callFunction(
        roster.client,
        removing ? "actors.role.remove" : "actors.role.set",
        removing ? { actor_id: actor.id } : { actor_id: actor.id, role },
      );
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
