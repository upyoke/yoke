import { callFunction } from "./universe_view_support.js";

export function revealActiveCompactDestination(windowNode, link) {
  if (
    !link ||
    typeof link.scrollIntoView !== "function" ||
    typeof windowNode.getComputedStyle !== "function"
  ) return;
  const navigation = link.parentNode;
  if (
    !navigation ||
    windowNode.getComputedStyle(navigation).flexDirection !== "row"
  ) return;
  link.scrollIntoView({ block: "nearest", inline: "nearest" });
}

export function loadWordmark(brand, assetUrl, isMounted) {
  Promise.resolve().then(() => globalThis.fetch(assetUrl))
    .then((response) => response.text())
    .then((svg) => { if (isMounted()) brand.innerHTML = svg; })
    .catch(() => { if (isMounted()) brand.textContent = "Yoke"; });
}

export function loadOrganizationName(client, orgContext, isMounted) {
  if (!orgContext) return;
  Promise.resolve().then(() => callFunction(client, "organizations.get", {}))
    .then((callResult) => {
      if (!isMounted()) return;
      const org = (callResult.envelope && callResult.envelope.result) || {};
      orgContext.textContent = org.name || "(unnamed org)";
    })
    .catch(() => { if (isMounted()) orgContext.textContent = ""; });
}

export function createHostSectionPlacement(resolvedSections) {
  function append(entry, viewHost, { scoped = false } = {}) {
    const hostSection = resolvedSections[entry.id];
    if (!hostSection) return;
    if (scoped && hostSection.placement === "beforeScope") return;
    viewHost.appendChild(hostSection.content);
  }

  function beforeScope(entry) {
    const hostSection = resolvedSections[entry.id];
    return (hostSection && hostSection.placement === "beforeScope")
      ? [hostSection.content] : [];
  }

  return { append, beforeScope };
}
