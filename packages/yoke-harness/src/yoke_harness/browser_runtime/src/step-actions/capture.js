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
 * Three framings, because `fullPage` only means "the whole content" for a
 * page that scrolls the document itself. An app that scrolls an inner
 * container leaves the document at viewport height, so `fullPage` there
 * photographs one screenful and silently drops everything below the fold --
 * a capture that looks complete and is not. Such a case names the scrolling
 * container as `target`: the element is scrolled into view and captured at
 * its own full size, whatever the viewport is showing.
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
