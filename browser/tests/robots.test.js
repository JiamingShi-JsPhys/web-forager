"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");

const { parseRobots, robotsAllows, checkRobots, clearCache } = require("../lib/robots");

const ROOT = path.join(__dirname, "..");
const ENTRY = path.join(ROOT, "run.js");
const FIXTURE = path.join(__dirname, "fixtures", "fake-bridge.js");
const HOME = path.join(__dirname, ".tmp-robots-home");

function serve(routes) {
  return new Promise((resolve) => {
    const server = http.createServer((request, response) => {
      const route = routes[request.url.split("?")[0]];
      if (!route) {
        response.writeHead(404, { "content-type": "text/plain" });
        response.end("not found");
        return;
      }
      response.writeHead(route.status || 200, { "content-type": "text/plain" });
      response.end(route.body || "");
    });
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port }));
  });
}

test("longest match wins and ties go to Allow", () => {
  const policy = parseRobots(
    ["User-agent: *", "Disallow: /private", "Allow: /private/ok", "Disallow: /private/ok/deep$"].join("\n"),
  );
  assert.equal(robotsAllows(policy, "https://example.org/private/x"), false);
  assert.equal(robotsAllows(policy, "https://example.org/private/ok/x"), true);
  assert.equal(robotsAllows(policy, "https://example.org/private/ok/deep"), false);
  assert.equal(robotsAllows(policy, "https://example.org/public"), true);

  const tie = parseRobots(["User-agent: *", "Disallow: /a", "Allow: /a"].join("\n"));
  assert.equal(robotsAllows(tie, "https://example.org/a"), true);
});

test("a more specific user-agent group wins over *", () => {
  const text = ["User-agent: *", "Disallow: /", "", "User-agent: WebForager-Browser", "Allow: /"].join("\n");
  const policy = parseRobots(text, "WebForager-Browser/1.2");
  assert.equal(robotsAllows(policy, "https://example.org/anything"), true);
});

test("checkRobots reads the live file and caches it per origin", async () => {
  clearCache();
  const { server, port } = await serve({
    "/robots.txt": { body: "User-agent: *\nDisallow: /blocked\n" },
  });
  try {
    const origin = `http://127.0.0.1:${port}`;
    const denied = await checkRobots(`${origin}/blocked/page`);
    assert.equal(denied.allowed, false);
    assert.equal(denied.status, 200);
    assert.match(denied.note || "", /robots\.txt read/);
    const allowed = await checkRobots(`${origin}/open/page`);
    assert.equal(allowed.allowed, true);
  } finally {
    server.close();
  }
});

test("a missing robots.txt allows, a failing one denies", async () => {
  clearCache();
  const { server, port } = await serve({});
  try {
    const decision = await checkRobots(`http://127.0.0.1:${port}/anything`);
    assert.equal(decision.status, 404);
    assert.equal(decision.allowed, true);
  } finally {
    server.close();
  }

  clearCache();
  const broken = await checkRobots("http://127.0.0.1:9/anything");
  assert.equal(broken.allowed, false);
  assert.match(broken.note, /unreachable/);
});

function runCli(args) {
  // Spawned, not spawnSync: the fixture server lives in this process, so the
  // event loop has to stay free while the child fetches robots.txt.
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [ENTRY, ...args], {
      env: {
        ...process.env,
        WEB_FORAGER_BROWSER_HOME: HOME,
        WEB_FORAGER_BRIDGE: `"${process.execPath}" "${FIXTURE}"`,
      },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("close", (status) => resolve({ status, stdout, stderr }));
  });
}

test("--strict-robots refuses a disallowed page with exit 3 and records the check", async () => {
  clearCache();
  const { server, port } = await serve({
    "/robots.txt": { body: "User-agent: *\nDisallow: /video/\n" },
  });
  fs.mkdirSync(HOME, { recursive: true });
  try {
    const origin = `http://127.0.0.1:${port}`;
    const result = await runCli([
      "--playbook",
      "bili-video",
      "--url",
      `${origin}/video/BV1aa411c7mD`,
      "--session",
      "strict",
      "--strict-robots",
      "--min-interval",
      "0",
      "--comment-scrolls",
      "0",
      "--agent",
    ]);
    assert.equal(result.status, 3, result.stderr);
    const payload = JSON.parse(result.stdout.trim().split("\n").pop());
    assert.equal(payload.ok, false);
    assert.equal(payload.error.code, "robots_denied");
  } finally {
    server.close();
  }
});

test("an allowed page records that robots.txt was consulted", async () => {
  clearCache();
  const { server, port } = await serve({
    "/robots.txt": { body: "User-agent: *\nAllow: /\n" },
  });
  fs.mkdirSync(HOME, { recursive: true });
  try {
    const origin = `http://127.0.0.1:${port}`;
    const result = await runCli([
      "--playbook",
      "bili-video",
      "--url",
      `${origin}/open/BV1aa411c7mD`,
      "--session",
      "allowed",
      "--strict-robots",
      "--min-interval",
      "0",
      "--comment-scrolls",
      "0",
      "--agent",
    ]);
    assert.equal(result.status, 8, result.stderr);
    const payload = JSON.parse(result.stdout.trim().split("\n").pop());
    assert.equal(payload.data.compliance.robots_checked, true);
    assert.equal(payload.data.compliance.checks[0].allowed, true);
    assert.equal(payload.data.records[0].compliance.robots_checked, true);
    assert.equal(payload.data.status, "degraded");
  } finally {
    server.close();
  }
});
