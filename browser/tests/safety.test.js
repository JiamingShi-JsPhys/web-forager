"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { isWriteAction, guardedClick, rateLimit } = require("../lib/safety");
const { contextFor, FakeBackend } = require("./helpers");

test("write-like labels are recognised", () => {
  assert.equal(isWriteAction({ name: "点赞" }), true);
  assert.equal(isWriteAction({ name: "投币" }), true);
  assert.equal(isWriteAction({ name: "收藏" }), true);
  assert.equal(isWriteAction({ name: "Follow" }), true);
  assert.equal(isWriteAction({ name: "下一个" }), false);
  assert.equal(isWriteAction({ name: "播放" }), false);
});

test("write-like clicks are denied by default", async () => {
  const ctx = contextFor(new FakeBackend([]));
  await assert.rejects(
    () => guardedClick(ctx, { name: "点赞", locator: "like" }),
    (error) => error.code === "confirmation_required",
  );
});

test("write-like clicks pass when explicitly allowed", async () => {
  const backend = new FakeBackend([]);
  const ctx = contextFor(backend, { allowWrite: true });
  await guardedClick(ctx, { name: "点赞", locator: "like" });
  assert.deepEqual(backend.actions[0], { action: "click", locator: "like" });
});

test("rate limiting waits between actions", async () => {
  const ctx = contextFor(new FakeBackend([]), { minInterval: 50 });
  await rateLimit(ctx);
  await rateLimit(ctx);
  assert.equal(ctx.sleeps.length, 1);
  assert.ok(ctx.sleeps[0] > 0 && ctx.sleeps[0] <= 50);
});
