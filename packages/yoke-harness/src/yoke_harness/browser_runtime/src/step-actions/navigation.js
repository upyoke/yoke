'use strict';

/**
 * Navigation/cursor action handlers: navigate, scroll, hover.
 *
 * Each handler takes (page, step, options[, refMap]) and returns
 * { success: boolean, artifacts?: string[] } or throws an Error.
 */

const { resolveTarget } = require('./target-helpers');

// Default timeout for scenario navigation actions.
const DEFAULT_TIMEOUT_MS = 5000;

/**
 * Resolve a URL -- prepends baseUrl to relative routes, passes absolute URLs through.
 *
 * @param {string} route
 * @param {string} baseUrl
 * @returns {string}
 */
function resolveUrl(route, baseUrl) {
  if (!route) return baseUrl;
  // Absolute URLs pass through
  if (/^https?:\/\//i.test(route)) return route;
  // Relative route -- prepend base URL
  const base = baseUrl.replace(/\/+$/, '');
  const rel = route.startsWith('/') ? route : '/' + route;
  return base + rel;
}

// Statuses that mean the server declined to show the page at all. A
// navigation landing here has not arrived anywhere a later step can
// read, click or photograph -- the body is a refusal, and a screenshot
// of a refusal looks like a rendered page.
const AUTH_REFUSAL_STATUSES = new Set([401, 403]);

/**
 * Execute a navigate action.
 */
async function executeNavigate(page, step, options) {
  const url = resolveUrl(step.route, options.baseUrl);
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  const response = await page.goto(url, { timeout, waitUntil: 'domcontentloaded' });
  const status = response ? response.status() : 0;
  if (AUTH_REFUSAL_STATUSES.has(status)) {
    throw new Error(
      `navigation to ${response.url()} was refused with HTTP ${status}: ` +
      'this page is an authentication refusal, not the screen the scenario ' +
      'asked for, and every following step would run against it. ' +
      'Establish the session first -- for a token-gated server, take one ' +
      '`snapshot screenshot` against the tokened URL on this same daemon ' +
      'and profile, then drive the remaining steps against bare paths.'
    );
  }
  return { success: true };
}

/**
 * Execute a scroll action.
 */
async function executeScroll(page, step, options, refMap) {
  if (step.target) {
    const locator = resolveTarget(page, step.target, refMap);
    const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
    await locator.scrollIntoViewIfNeeded({ timeout });
  } else {
    // Scroll the page by the specified amount or to bottom
    const x = step.x || 0;
    const y = step.y || 300;
    await page.mouse.wheel(x, y);
  }
  return { success: true };
}

/**
 * Execute a hover action.
 */
async function executeHover(page, step, options, refMap) {
  const locator = resolveTarget(page, step.target, refMap);
  const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
  await locator.hover({ timeout });
  return { success: true };
}

module.exports = {
  resolveUrl,
  executeNavigate,
  executeScroll,
  executeHover,
};
