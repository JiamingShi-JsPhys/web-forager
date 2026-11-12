"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { assertPublicUrl, isPublicRequestUrl, isBlockedIp } = require("../lib/netguard");

test("private, loopback and metadata addresses are blocked", () => {
  for (const ip of [
    "127.0.0.1",
    "10.1.2.2",
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",
    "100.64.0.1",
    "0.0.0.0",
    "::1",
    "::ffff:127.0.0.1",
    "fc00::1",
    "fe80::1",
  ]) {
    assert.equal(isBlockedIp(ip), true, `${ip} should be blocked`);
  }
});

test("public addresses pass", () => {
  assert.equal(isBlockedIp("8.8.8.8"), false);
  assert.equal(isBlockedIp("2001:4860:4860::8888"), false);
});

test("navigation to a private literal throws an actor error", async () => {
  await assert.rejects(
    () => assertPublicUrl("http://169.254.169.254/latest/meta-data/", { allowPrivate: false }),
    (error) => error.code === "unsafe_url",
  );
});

test("localhost names are refused", async () => {
  for (const url of ["http://localhost:9222/", "http://box.local/", "http://api.internal/"]) {
    await assert.rejects(() => assertPublicUrl(url, { allowPrivate: false }));
  }
});

test("a decimal IPv4 spelling is normalised before the check", async () => {
  // WHATWG URL turns http://2130706433/ into http://127.0.0.1/.
  await assert.rejects(() => assertPublicUrl("http://2130706433/", { allowPrivate: false }));
});

test("non-http schemes are refused for navigation", async () => {
  await assert.rejects(
    () => assertPublicUrl("file:///C:/Windows/win.ini", { allowPrivate: false }),
    (error) => error.code === "unsafe_url",
  );
});

test("subresources may use data: and blob: without a host check", async () => {
  assert.equal(await isPublicRequestUrl("data:image/png;base64,AAAA", { allowPrivate: false }), true);
  assert.equal(await isPublicRequestUrl("blob:https://example.org/abc", { allowPrivate: false }), true);
});

test("allowPrivate opts out for intranet targets", async () => {
  await assertPublicUrl("http://127.0.0.1:8080/", { allowPrivate: true });
  assert.equal(await isPublicRequestUrl("http://127.0.0.1:8080/", { allowPrivate: true }), true);
});

test("guarded navigation blocks a private target before the backend runs", async () => {
  const { guardedGoto } = require("../lib/safety");
  let called = false;
  const ctx = {
    options: { minInterval: 0, allowPrivate: false },
    compliance: { checks: [] },
    trace: [],
    lastActionAt: 0,
    sleep: async () => {},
    backend: {
      async goto() {
        called = true;
        return { url: "http://127.0.0.1/" };
      },
    },
  };
  await assert.rejects(
    () => guardedGoto(ctx, "http://127.0.0.1/"),
    (error) => error.code === "unsafe_url",
  );
  assert.equal(called, false);
});
