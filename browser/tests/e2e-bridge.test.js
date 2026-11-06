"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ROOT = path.join(__dirname, "..");
const ENTRY = path.join(ROOT, "run.js");
const FIXTURE = path.join(__dirname, "fixtures", "fake-bridge.js");
const HOME = path.join(__dirname, ".tmp-e2e-home");

function run(args) {
  fs.mkdirSync(HOME, { recursive: true });
  const result = spawnSync(process.execPath, [ENTRY, ...args], {
    encoding: "utf8",
    env: {
      ...process.env,
      WEB_FORAGER_BROWSER_HOME: HOME,
      WEB_FORAGER_BRIDGE: `"${process.execPath}" "${FIXTURE}"`,
    },
  });
  const line = result.stdout
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
    .pop();
  return { status: result.status, payload: line ? JSON.parse(line) : null, stderr: result.stderr };
}

test("the CLI runs a playbook end to end through the bridge protocol", () => {
  const result = run([
    "--playbook",
    "bili-video",
    "--url",
    "https://www.bilibili.com/video/BV1aa411c7mD",
    "--session",
    "e2e-video",
    "--comment-scrolls",
    "0",
    "--min-interval",
    "0",
    "--agent",
  ]);

  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.payload.ok, true);
  assert.equal(result.payload.data.backend.name, "iab");
  assert.equal(result.payload.data.backend.capabilities.observe, true);
  assert.equal(result.payload.data.records[0].metadata.bvid, "BV1aa411c7mD");
  assert.ok(result.payload.data.records[0].markdown.includes("评论一"));
  assert.ok(
    result.payload.data.records[0].interaction_trace.some((step) => step.action === "goto"),
  );
});

test("danmaku observation flows through the same bridge", () => {
  const result = run([
    "--playbook",
    "bili-danmaku",
    "--url",
    "https://www.bilibili.com/video/BV1aa411c7mD",
    "--session",
    "e2e-danmaku",
    "--observe-ms",
    "500",
    "--min-interval",
    "0",
    "--backend",
    "extension",
    "--agent",
  ]);

  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.payload.data.summary.source, "network");
  assert.equal(result.payload.data.summary.danmaku, 1);
  assert.equal(result.payload.data.backend.name, "extension");
});

test("an unknown backend exits 2", () => {
  const result = run(["--playbook", "bili-feed", "--backend", "selenium", "--agent"]);
  assert.equal(result.status, 2);
  assert.equal(result.payload.error.code, "argument");
});
