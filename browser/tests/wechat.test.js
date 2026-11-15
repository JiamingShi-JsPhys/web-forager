"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { contextFor, FakeBackend } = require("./helpers");
const wechat = require("../playbooks/wechat-dig");
const { bodyText } = require("../lib/snapshot");

const ARTICLE = "https://mp.weixin.qq.com/s/example";

test("bodyText prefers one content node over leaf fragments", () => {
  const snapshot = {
    nodes: [
      { role: "content", name: "完整正文第一段。完整正文第二段。" },
      { role: "text", name: "残缺片段" },
    ],
  };
  assert.equal(bodyText(snapshot), "完整正文第一段。完整正文第二段。");
});

test("wechat-dig captures the article body", async () => {
  const page = {
    url: ARTICLE,
    title: "一篇文章",
    nodes: [
      { role: "heading", name: "一篇文章" },
      { role: "content", name: "这是正文第一段。".repeat(20) },
    ],
  };
  const backend = new FakeBackend([page]);
  const ctx = contextFor(backend, { url: ARTICLE });
  const result = await wechat.run(ctx);

  assert.equal(result.summary.status, "ok");
  assert.equal(result.summary.title, "一篇文章");
  assert.equal(ctx.records.length, 1);
  assert.equal(ctx.records[0].metadata.site, "wechat");
  assert.ok(ctx.records[0].markdown.includes("这是正文第一段"));
  assert.deepEqual(backend.actions.map((action) => action.action), ["goto"]);
});

test("wechat-dig reports the environment check as blocked", async () => {
  const wall = {
    url: ARTICLE,
    title: "微信公众平台",
    nodes: [
      { role: "text", name: "环境异常" },
      { role: "text", name: "当前环境异常，完成验证后即可继续访问。" },
      { role: "button", name: "去验证" },
    ],
  };
  const backend = new FakeBackend([wall]);
  const ctx = contextFor(backend, { url: ARTICLE });

  await assert.rejects(
    () => wechat.run(ctx),
    (error) => error.code === "blocked" && /environment-check/.test(error.message),
  );
  assert.equal(ctx.records.length, 0);
});

test("wechat-dig recognises a captcha redirect with no page text", async () => {
  const wall = {
    url: "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token=x",
    title: "",
    nodes: [],
  };
  const backend = new FakeBackend([wall]);
  const ctx = contextFor(backend, { url: ARTICLE });

  await assert.rejects(
    () => wechat.run(ctx),
    (error) => error.code === "blocked" && /environment-check/.test(error.message),
  );
});

test("wechat-dig refuses a non-WeChat URL", async () => {
  const ctx = contextFor(new FakeBackend([]), { url: "https://example.org/a" });
  await assert.rejects(
    () => wechat.run(ctx),
    (error) => error.code === "argument",
  );
});
