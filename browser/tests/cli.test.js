"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ENTRY = path.join(__dirname, "..", "run.js");

function run(args) {
  return spawnSync(process.execPath, [ENTRY, ...args], {
    encoding: "utf8",
    env: {
      ...process.env,
      // A developer machine may export WEB_FORAGER_BRIDGE; these tests are
      // about the no-bridge path, so clear it explicitly.
      WEB_FORAGER_BRIDGE: "",
      WEB_FORAGER_BROWSER_HOME: path.join(__dirname, ".tmp-home"),
    },
  });
}

test("--version prints the package version", () => {
  const result = run(["--version"]);
  assert.equal(result.status, 0);
  assert.match(result.stdout, /web-forager-browser 1\.1\.0/);
});

test("--list --agent lists the seven playbooks", () => {
  const result = run(["--list", "--agent"]);
  assert.equal(result.status, 0);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.deepEqual(
    payload.data.map((item) => item.name).sort(),
    ["bili-chain", "bili-danmaku", "bili-feed", "bili-video", "search-dig", "xhs-dig", "zhihu-dig"],
  );
});

test("--dry-run plans without a browser", () => {
  const result = run(["--playbook", "bili-feed", "--dry-run", "--agent"]);
  assert.equal(result.status, 0);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.equal(payload.data.backend, "unavailable");
  assert.equal(payload.data.playbook, "bili-feed");
});

test("a missing argument exits 2 with a structured error", () => {
  const result = run(["--playbook", "bili-video", "--agent"]);
  assert.equal(result.status, 2);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, false);
  assert.equal(payload.error.code, "argument");
});

test("a missing backend exits 3 with a hint", () => {
  const result = run([
    "--playbook",
    "bili-video",
    "--url",
    "https://www.bilibili.com/video/BV1aa411c7mD",
    "--agent",
    "--min-interval",
    "0",
  ]);
  assert.equal(result.status, 3);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.error.code, "backend_unavailable");
  assert.match(payload.error.hint, /WEB_FORAGER_BRIDGE/);
});

test("an unknown playbook exits 2", () => {
  const result = run(["--playbook", "nope", "--agent"]);
  assert.equal(result.status, 2);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.error.code, "argument");
});

test("the bundled bridge is found without any configuration", () => {
  const env = {
    ...process.env,
    WEB_FORAGER_BROWSER_HOME: path.join(__dirname, ".tmp-home"),
  };
  delete env.WEB_FORAGER_BRIDGE;
  const result = spawnSync(
    process.execPath,
    [ENTRY, "--playbook", "bili-feed", "--dry-run", "--agent"],
    { encoding: "utf8", env },
  );
  assert.equal(result.status, 0);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.ok, true);
  assert.equal(payload.data.backend, "iab");
  assert.equal(payload.data.backend_detail.bridge, "configured");
});
