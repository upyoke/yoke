import { buildUniverseRoute } from "./universe_navigation.js";

const POSITIVE_INTEGER = /^\d+$/;
const PUBLIC_ITEM_REF = /^[A-Za-z][A-Za-z0-9]*-(\d+)$/;

function canonicalPositiveInteger(value) {
  const text = String(value ?? "").trim();
  if (!POSITIVE_INTEGER.test(text)) return null;
  const number = Number(text);
  return Number.isSafeInteger(number) && number > 0 ? String(number) : null;
}

export function itemDrillInHref({
  projectId,
  projectSequence = null,
  publicRef = null,
} = {}) {
  const project = canonicalPositiveInteger(projectId);
  if (!project) return null;

  const rawRef = String(publicRef ?? "").trim();
  const refMatch = rawRef ? PUBLIC_ITEM_REF.exec(rawRef) : null;
  if (rawRef && !refMatch) return null;

  const explicitSequence = String(projectSequence ?? "").trim();
  const sequence = explicitSequence
    ? canonicalPositiveInteger(explicitSequence)
    : canonicalPositiveInteger(refMatch?.[1]);
  if (!sequence) return null;
  if (
    refMatch &&
    canonicalPositiveInteger(refMatch[1]) !== sequence
  ) return null;

  return buildUniverseRoute("items", project, sequence);
}
