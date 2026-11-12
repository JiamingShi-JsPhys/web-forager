"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { searchVideos, stripTags } = require("../lib/bili-api");

function withFetch(stub, body) {
  const saved = global.fetch;
  const savedEnv = process.env.WEB_FORAGER_BILI_API;
  delete process.env.WEB_FORAGER_BILI_API;
  global.fetch = stub;
  return Promise.resolve()
    .then(body)
    .finally(() => {
      global.fetch = saved;
      if (savedEnv === undefined) delete process.env.WEB_FORAGER_BILI_API;
      else process.env.WEB_FORAGER_BILI_API = savedEnv;
    });
}

test("searchVideos maps titles, urls and bvids", () =>
  withFetch(
    async (url) => {
      if (String(url).includes("api.bilibili.com")) {
        return {
          ok: true,
          json: async () => ({
            code: 0,
            data: {
              result: [
                {
                  title: '张<em class="keyword">三</em>解析',
                  arcurl: "https://www.bilibili.com/video/BV1xx411c7mD/",
                  bvid: "BV1xx411c7mD",
                  author: "测试UP主",
                  play: 12,
                  duration: "03:45",
                  description: "简介",
                },
              ],
            },
          }),
        };
      }
      return { ok: true, headers: new Map(), json: async () => ({}) };
    },
    async () => {
      const items = await searchVideos("张三", 5);
      assert.equal(items.length, 1);
      assert.equal(items[0].title, "张三解析");
      assert.equal(items[0].bvid, "BV1xx411c7mD");
      assert.equal(items[0].url, "https://www.bilibili.com/video/BV1xx411c7mD/");
      assert.equal(items[0].source, "bilibili-api");
    },
  ));

test("searchVideos refuses a non-zero API code", () =>
  withFetch(
    async (url) => {
      if (String(url).includes("api.bilibili.com")) {
        return { ok: true, json: async () => ({ code: -412, message: "请求被拦截" }) };
      }
      return { ok: true, headers: new Map(), json: async () => ({}) };
    },
    async () => {
      await assert.rejects(() => searchVideos("test", 3), /code -412/);
    },
  ));

test("searchVideos stays out of the way when disabled", async () => {
  const saved = process.env.WEB_FORAGER_BILI_API;
  process.env.WEB_FORAGER_BILI_API = "off";
  try {
    await assert.rejects(() => searchVideos("test", 3), /disabled/);
  } finally {
    if (saved === undefined) delete process.env.WEB_FORAGER_BILI_API;
    else process.env.WEB_FORAGER_BILI_API = saved;
  }
});

test("the buvid3 cookie is sent but never appears in the result", () => {
  let apiCookie = "";
  return withFetch(
    async (url, options) => {
      const headers = (options && options.headers) || {};
      if (String(url).includes("api.bilibili.com")) {
        apiCookie = headers.cookie || "";
        return {
          ok: true,
          json: async () => ({
            code: 0,
            data: { result: [{ title: "t", bvid: "BV1", arcurl: "https://b/x" }] },
          }),
        };
      }
      return {
        ok: true,
        headers: { getSetCookie: () => ["buvid3=SECRETVALUE; Path=/; HttpOnly"] },
        json: async () => ({}),
      };
    },
    async () => {
      const items = await searchVideos("q", 1);
      assert.match(apiCookie, /buvid3=SECRETVALUE/);
      assert.doesNotMatch(JSON.stringify(items), /SECRETVALUE/);
    },
  );
});

test("stripTags removes markup and entities", () => {
  assert.equal(stripTags('<em class="keyword">张</em>三'), "张三");
  assert.equal(stripTags("a &amp; b"), "a & b");
});
