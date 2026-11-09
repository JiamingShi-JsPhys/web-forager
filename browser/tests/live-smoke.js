#!/usr/bin/env node
"use strict";

// Opt-in smoke test against the live sites. It is not part of the default
// suite: it needs a real bridge, a network, and a logged-in profile for some
// pages. Run it before a release:
//
//   WEB_FORAGER_LIVE=1 WEB_FORAGER_BRIDGE="node bridges/playwright-bridge.js" npm run test:live
//
// Exit codes: 0 = passed or skipped, 1 = a live selector no longer works.

const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ENTRY = path.join(__dirname, "..", "run.js");

function run(args) {
  const result = spawnSync(process.execPath, [ENTRY, ...args, "--agent"], { encoding: "utf8" });
  const line = result.stdout
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
    .pop();
  let payload = null;
  try {
    payload = line ? JSON.parse(line) : null;
  } catch {
    payload = null;
  }
  return { status: result.status, payload, stderr: result.stderr };
}

function main() {
  if (process.env.WEB_FORAGER_LIVE !== "1") {
    process.stdout.write("live smoke: skipped (set WEB_FORAGER_LIVE=1 and WEB_FORAGER_BRIDGE to run it)\n");
    return 0;
  }
  if (!process.env.WEB_FORAGER_BRIDGE) {
    process.stdout.write("live smoke: skipped (WEB_FORAGER_BRIDGE is not set)\n");
    return 0;
  }

  const failures = [];
  const cases = [
    {
      name: "bili-feed reads the home feed",
      args: ["--playbook", "bili-feed", "--max-screens", "1", "--max-items", "3", "--session", "live-feed"],
      check: (payload) => payload.data.summary.captured > 0,
    },
    {
      name: "bili-video reads one public video",
      args: [
        "--playbook",
        "bili-video",
        "--url",
        "https://www.bilibili.com/video/BV1GJ411x7h7",
        "--comment-scrolls",
        "1",
        "--session",
        "live-video",
      ],
      check: (payload) => Boolean(payload.data.summary.bvid),
    },
  ];

  for (const item of cases) {
    const result = run(item.args);
    const ok = Boolean(result.payload && result.payload.data) && item.check(result.payload);
    process.stdout.write(`${ok ? "ok  " : "FAIL"}  ${item.name} (exit ${result.status})\n`);
    if (!ok) failures.push(item.name);
  }

  if (failures.length) {
    process.stdout.write(`live smoke: ${failures.length} case(s) failed: ${failures.join(", ")}\n`);
    return 1;
  }
  process.stdout.write("live smoke: all cases passed\n");
  return 0;
}

process.exitCode = main();
