"use strict";

// Answer "why did my first browser run fail" before the playbook does.
//
// Two layers can be missing and they produce different errors: the playwright
// npm package (the bridge exits with a module error) and the Chromium binary it
// downloads separately (the launch fails). The report names both, plus where the
// bridge, the profile and Node itself are.

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { createRequire } = require("node:module");

const { BUNDLED_BRIDGE, resolveBridge } = require("./bridge");

const DEFAULT_PROFILE = path.join(os.homedir(), ".web-forager", "browser", "profile");

function resolveFrom(root, name) {
  try {
    return createRequire(path.join(root, "doctor.js")).resolve(name);
  } catch (error) {
    return "";
  }
}

function playwrightReport(extraRoots = []) {
  const roots = [...extraRoots, path.dirname(BUNDLED_BRIDGE), process.cwd()];
  let resolved = "";
  for (const root of roots) {
    resolved = resolveFrom(root, "playwright");
    if (resolved) break;
  }
  if (!resolved) {
    return {
      installed: false,
      hint: "npm i playwright && npx playwright install chromium",
    };
  }
  let version = "";
  let chromium = "";
  try {
    const playwright = require(resolved);
    version = (playwright && playwright._version) || "";
    if (!version) {
      try {
        version = require(path.join(path.dirname(resolved), "package.json")).version || "";
      } catch (error) {
        version = "";
      }
    }
    chromium = playwright.chromium.executablePath();
  } catch (error) {
    return { installed: true, path: resolved, version, chromium: "", error: String(error.message || error) };
  }
  const chromiumInstalled = Boolean(chromium) && fs.existsSync(chromium);
  return {
    installed: true,
    path: resolved,
    version,
    chromium: chromiumInstalled ? chromium : "",
    chromium_installed: chromiumInstalled,
    ...(chromiumInstalled ? {} : { hint: "npx playwright install chromium" }),
  };
}

function doctorReport() {
  const command = resolveBridge("");
  const bridgePath = command.startsWith("node ") ? command.slice(5).replace(/^"|"$/g, "") : "";
  const playwright = playwrightReport(bridgePath ? [path.dirname(bridgePath)] : []);
  const profile = (process.env.WEB_FORAGER_BROWSER_PROFILE || "").trim();
  const profileDir = ["off", "0", "false", "none"].includes(profile.toLowerCase())
    ? ""
    : path.resolve(profile || DEFAULT_PROFILE);
  const hints = [];
  if (!command) hints.push("No bridge command: install the playwright package or set WEB_FORAGER_BRIDGE.");
  if (!playwright.installed) hints.push("Playwright is not resolvable: npm i playwright.");
  if (playwright.installed && playwright.chromium_installed === false) {
    hints.push("Chromium is not downloaded: npx playwright install chromium.");
  }
  if (!profileDir) hints.push("The browser profile is disabled; each run starts without cookies.");
  return {
    ok: Boolean(command) && playwright.installed && playwright.chromium_installed !== false,
    node: process.version,
    bridge: {
      command: command || "",
      bundled: Boolean(bridgePath) && path.resolve(bridgePath) === path.resolve(BUNDLED_BRIDGE),
      exists: Boolean(bridgePath) && fs.existsSync(bridgePath),
    },
    playwright,
    profile: { dir: profileDir, exists: profileDir ? fs.existsSync(profileDir) : false },
    cdp: process.env.WEB_FORAGER_BROWSER_CDP || "",
    hints,
  };
}

module.exports = { doctorReport, DEFAULT_PROFILE };
