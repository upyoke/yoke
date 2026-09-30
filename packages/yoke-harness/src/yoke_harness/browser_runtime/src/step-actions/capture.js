'use strict';

/**
 * Capture action handler: screenshot.
 *
 * executeScreenshot(page, step, options) -> { success: true, artifacts?: string[] }
 */

const path = require('path');

const { resolvePresenceTarget } = require('./target-helpers');

// Default timeout for bringing a capture target into view.
const DEFAULT_TIMEOUT_MS = 5000;

function screenshotBasename(step) {
  const timestamp = Date.now();
  if (typeof step.label !== 'string') {
    return `screenshot-${timestamp}.png`;
  }
  const slug = step.label
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
  if (!slug) {
    return `screenshot-${timestamp}.png`;
  }
  return `screenshot-${slug}-${timestamp}.png`;
}

/**
 * Execute a screenshot action.
 *
 * Captures a screenshot when capture is true, returns the path in artifacts.
 * `label` names the file so the capture matches the step's own account.
 *
 * `target` frames the capture on one element instead of on the screen. A
 * page capture can only ever show what is in view -- `fullPage` grows with
 * the document, so on an app that scrolls an inner container it photographs
 * the container's first screenful and silently drops the rest, and an
 * element below the fold does not appear at all. Naming the element scrolls
 * it into view and captures its own box, so the evidence is the panel being
 * judged at the size it renders at, wherever it sits on the page.
 *
 * The box is what the element shows, not its scrollable content: a capture
 * cannot honestly photograph pixels the page never painted. A case covering
 * a long inner-scrolling list pairs `scroll` with a capture per screenful.
 */
async function executeScreenshot(page, step, options, refMap) {
  if (!step.capture) {
    return { success: true };
  }

  const outputDir = options.outputDir || '/tmp';
  const screenshotPath = path.join(outputDir, screenshotBasename(step));

  if (typeof step.target === 'string' && step.target.trim()) {
    const timeout = step.timeout_ms || options.timeout || DEFAULT_TIMEOUT_MS;
    // Presence resolution: a container named by a repeated-component
    // selector is still a legitimate capture subject, and the first match is
    // what "photograph that panel" means.
    const locator = resolvePresenceTarget(page, step.target, refMap);
    await locator.scrollIntoViewIfNeeded({ timeout });
    await locator.screenshot({ path: screenshotPath, timeout });
    return { success: true, artifacts: [screenshotPath] };
  }

  await page.screenshot({ path: screenshotPath, fullPage: !!step.fullPage });
  return { success: true, artifacts: [screenshotPath] };
}

module.exports = { executeScreenshot };
