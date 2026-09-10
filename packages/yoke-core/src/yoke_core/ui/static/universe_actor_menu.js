// The actor chip and its menu: who the viewer is acting as, and the one
// place the person's own page is reached from. Profile is not a sidebar
// destination because it is about the person, not the universe.
//
// The chip is drawn immediately from what the shell already knows and then
// refreshed from one profile.get read, which also carries the person's
// time-zone preference so every absolute time on the page honours it.

import { buildUniverseRoute } from "./universe_navigation.js";
import { setDisplayTimeZone } from "./universe_time.js";
import { callFunction, el } from "./universe_view_support.js";

function avatarText(actor, name) {
  return actor.kind === "system" ? "⚙" : name.slice(0, 1);
}

function actorKindText(actor) {
  if (actor.id !== undefined && actor.id !== null) return `actor ${actor.id}`;
  if (actor.kind === "system") return actor.systemComponent || "system";
  return "";
}

export function createActorMenu(documentNode, client, actor) {
  const host = el(documentNode, "span", "actor-menu-host");
  const chip = el(documentNode, "button", "actor-chip");
  chip.type = "button";
  chip.setAttribute("aria-haspopup", "menu");
  chip.setAttribute("aria-expanded", "false");
  const avatar = el(documentNode, "span", "actor-avatar");
  const name = el(documentNode, "span", "actor-name");
  const kind = el(documentNode, "span", "actor-kind");
  chip.appendChild(avatar);
  chip.appendChild(name);
  chip.appendChild(kind);
  host.appendChild(chip);

  const menu = el(documentNode, "div", "actor-menu");
  menu.setAttribute("role", "menu");
  menu.hidden = true;
  const heading = el(documentNode, "div", "actor-menu-heading");
  const profileLink = el(documentNode, "a", "actor-menu-link", "Profile");
  profileLink.href = buildUniverseRoute("profile", null);
  profileLink.setAttribute("role", "menuitem");
  menu.appendChild(heading);
  menu.appendChild(profileLink);
  host.appendChild(menu);

  const draw = (facts) => {
    const shownName = facts.name || `actor ${facts.id}`;
    avatar.textContent = avatarText(facts, shownName);
    name.textContent = shownName;
    kind.textContent = actorKindText(facts);
    kind.hidden = !kind.textContent;
    heading.textContent = facts.email
      ? `${shownName} · ${facts.email}` : shownName;
  };
  draw({ ...actor, name: actor.label });

  const setOpen = (open) => {
    menu.hidden = !open;
    chip.setAttribute("aria-expanded", open ? "true" : "false");
  };
  chip.addEventListener("click", (event) => {
    event.stopPropagation();
    setOpen(menu.hidden);
  });
  profileLink.addEventListener("click", () => setOpen(false));
  // A click anywhere else closes the menu; a headless document has no
  // listeners to offer and the menu still toggles from the chip.
  if (typeof documentNode.addEventListener === "function") {
    documentNode.addEventListener("click", () => setOpen(false));
  }

  // The read may refuse (no bound actor), fail, or be unsupported by the
  // client; the chip then keeps the shell's own label, which is still true.
  const applyProfile = (result) => {
    if (!(result && result.status === 200 && result.envelope.success)) return;
    const profile = result.envelope.result;
    setDisplayTimeZone(profile.preferences?.time_zone || "");
    draw({
      ...actor,
      id: profile.actor.id,
      kind: profile.actor.kind,
      name: profile.actor.name,
      email: profile.identity?.email || "",
    });
  };
  if (client) {
    try {
      Promise.resolve(callFunction(client, "profile.get", {}))
        .then(applyProfile)
        .catch(() => {});
    } catch (syncError) {
      // A client that throws on an unknown function is a client without
      // a profile; the chip stays as drawn.
    }
  }
  return host;
}
