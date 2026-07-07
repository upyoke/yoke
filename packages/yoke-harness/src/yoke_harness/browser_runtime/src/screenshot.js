'use strict';

/**
 * Annotated screenshot with ref badges.
 *
 * Exports:
 *   annotatedScreenshot(page, refMap, options) -> { imagePath, refs, url, timestamp, viewport }
 *   plainScreenshot(page, options)             -> { imagePath, url, timestamp, viewport }
 *
 * Badge rendering injects temporary overlay elements via page.evaluate,
 * captures the screenshot, then removes the overlays. The page is not
 * permanently modified.
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

/**
 * Generate a temp file path for a screenshot.
 */
function defaultOutputPath() {
  const ts = Date.now();
  return path.join(os.tmpdir(), `yoke-screenshot-${ts}-${process.pid}.png`);
}

/**
 * Inject numbered badge overlays on elements identified by their locator strings.
 *
 * Each badge is a small numbered circle positioned at the top-left corner of
 * the element. Returns the cleanup function ID for later removal.
 *
 * @param {import('playwright').Page} page
 * @param {Object} refMap - { [refId]: locatorString }
 * @returns {Promise<void>}
 */
async function injectBadges(page, refMap) {
  await page.evaluate((refs) => {
    // Create a container for all badge overlays
    const container = document.createElement('div');
    container.id = '__yoke_badge_container__';
    container.style.cssText = 'position:absolute;top:0;left:0;width:0;height:0;overflow:visible;z-index:2147483647;pointer-events:none;';
    document.body.appendChild(container);

    for (const [refId, locator] of Object.entries(refs)) {
      // Resolve the locator to an element
      let el = null;

      if (locator.startsWith('[data-testid=')) {
        // [data-testid="value"]
        el = document.querySelector(locator);
      } else if (locator.startsWith('#')) {
        // CSS ID selector
        el = document.querySelector(locator);
      } else if (locator.startsWith('role=')) {
        // role=roleName[name="value"] or role=roleName >> nth=N
        const nthMatch = locator.match(/^role=(\w+)\s*>>\s*nth=(\d+)$/);
        const nameMatch = locator.match(/^role=(\w+)\[name="(.+)"\]$/);

        if (nameMatch) {
          const [, role, name] = nameMatch;
          // Query elements with matching role and accessible name
          const candidates = document.querySelectorAll(`[role="${role}"]`);
          for (const c of candidates) {
            const accName = c.getAttribute('aria-label') || c.textContent.trim();
            if (accName === name) {
              el = c;
              break;
            }
          }
          // Also check implicit role mappings
          if (!el) {
            const implicitMap = {
              button: 'button',
              link: 'a',
              textbox: 'input[type="text"],input[type="email"],input[type="password"],input[type="search"],input[type="tel"],input[type="url"],input:not([type]),textarea',
              checkbox: 'input[type="checkbox"]',
              radio: 'input[type="radio"]',
              combobox: 'select',
              heading: 'h1,h2,h3,h4,h5,h6',
              navigation: 'nav',
              main: 'main',
              form: 'form',
            };
            const selector = implicitMap[role];
            if (selector) {
              const elems = document.querySelectorAll(selector);
              for (const e of elems) {
                const accName = e.getAttribute('aria-label') || e.textContent.trim();
                if (accName === name) {
                  el = e;
                  break;
                }
              }
            }
          }
        } else if (nthMatch) {
          const [, role, idx] = nthMatch;
          const candidates = document.querySelectorAll(`[role="${role}"]`);
          const implicitMap = {
            button: 'button',
            link: 'a',
            textbox: 'input[type="text"],input[type="email"],input[type="password"],input[type="search"],input[type="tel"],input[type="url"],input:not([type]),textarea',
            checkbox: 'input[type="checkbox"]',
            radio: 'input[type="radio"]',
            combobox: 'select',
          };
          const all = Array.from(candidates);
          const selector = implicitMap[role];
          if (selector) {
            all.push(...document.querySelectorAll(selector));
          }
          el = all[parseInt(idx, 10)] || null;
        }
      }

      if (!el) continue;

      const rect = el.getBoundingClientRect();
      const scrollX = window.scrollX || document.documentElement.scrollLeft;
      const scrollY = window.scrollY || document.documentElement.scrollTop;

      const badge = document.createElement('div');
      badge.className = '__yoke_badge__';
      badge.textContent = refId;
      badge.style.cssText = [
        'position:absolute',
        `top:${rect.top + scrollY - 8}px`,
        `left:${rect.left + scrollX - 8}px`,
        'width:20px',
        'height:20px',
        'border-radius:50%',
        'background:#e53e3e',
        'color:#fff',
        'font-size:11px',
        'font-weight:bold',
        'font-family:Arial,sans-serif',
        'display:flex',
        'align-items:center',
        'justify-content:center',
        'line-height:1',
        'box-shadow:0 1px 3px rgba(0,0,0,0.4)',
        'pointer-events:none',
        'z-index:2147483647',
      ].join(';');

      container.appendChild(badge);
    }
  }, refMap);
}

/**
 * Remove all injected badge overlays from the page.
 *
 * @param {import('playwright').Page} page
 * @returns {Promise<void>}
 */
async function removeBadges(page) {
  await page.evaluate(() => {
    const container = document.getElementById('__yoke_badge_container__');
    if (container) container.remove();
  });
}

/**
 * Capture an annotated screenshot with numbered badge overlays.
 *
 * @param {import('playwright').Page} page - Playwright page (already navigated)
 * @param {Object} refMap - { [refId]: locatorString } from buildRefMap
 * @param {Object} [options]
 * @param {string} [options.outputPath] - Path to write the PNG; defaults to temp dir
 * @param {{ width: number, height: number }} [options.viewport] - Viewport to set before capture
 * @returns {Promise<{ imagePath: string, refs: Object, url: string, timestamp: string, viewport: { width: number, height: number } }>}
 */
async function annotatedScreenshot(page, refMap, options = {}) {
  const outputPath = options.outputPath || defaultOutputPath();

  // Set viewport if requested
  if (options.viewport) {
    await page.setViewportSize(options.viewport);
  }

  // Ensure output directory exists
  const dir = path.dirname(outputPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  // AC-5: Inject badges, capture, then remove
  await injectBadges(page, refMap);
  try {
    await page.screenshot({ path: outputPath, fullPage: false });
  } finally {
    await removeBadges(page);
  }

  const vp = page.viewportSize();

  return {
    imagePath: outputPath,
    refs: refMap,
    url: page.url(),
    timestamp: new Date().toISOString(),
    viewport: { width: vp.width, height: vp.height },
  };
}

/**
 * Capture a plain screenshot (no badge overlays).
 *
 * @param {import('playwright').Page} page - Playwright page (already navigated)
 * @param {Object} [options]
 * @param {string} [options.outputPath] - Path to write the PNG; defaults to temp dir
 * @param {{ width: number, height: number }} [options.viewport] - Viewport to set before capture
 * @returns {Promise<{ imagePath: string, url: string, timestamp: string, viewport: { width: number, height: number } }>}
 */
async function plainScreenshot(page, options = {}) {
  const outputPath = options.outputPath || defaultOutputPath();

  // Set viewport if requested
  if (options.viewport) {
    await page.setViewportSize(options.viewport);
  }

  // Ensure output directory exists
  const dir = path.dirname(outputPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  await page.screenshot({ path: outputPath, fullPage: false });

  const vp = page.viewportSize();

  return {
    imagePath: outputPath,
    url: page.url(),
    timestamp: new Date().toISOString(),
    viewport: { width: vp.width, height: vp.height },
  };
}

module.exports = { annotatedScreenshot, plainScreenshot };
