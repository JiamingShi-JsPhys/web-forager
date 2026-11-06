"use strict";

const { ActorError } = require("../lib/errors");
const { guardedGoto } = require("../lib/safety");
const { extractVideoMeta, findDanmaku, bvidFrom } = require("../lib/snapshot");
const { markVisited } = require("../lib/session");

const NAME = "bili-danmaku";

module.exports = {
  name: NAME,
  description: "Capture visible danmaku for one Bilibili video, falling back to passive bridge observation (experimental).",
  requires: ["url"],

  async run(ctx) {
    let url = ctx.options.url;
    if (!url && ctx.options.bvid) url = `https://www.bilibili.com/video/${ctx.options.bvid}`;
    if (!url) throw new ActorError("argument", "bili-danmaku needs --url or --bvid");

    await guardedGoto(ctx, url);
    markVisited(ctx.session, url);

    const snapshot = await ctx.backend.snapshot();
    const meta = extractVideoMeta(snapshot);
    let entries = findDanmaku(snapshot);
    let source = "dom";

    if (!entries.length && typeof ctx.backend.observe === "function") {
      try {
        const observed = await ctx.backend.observe("danmaku", Number(ctx.options.observeMs || 3000));
        entries = (observed && (observed.entries || observed.events)) || [];
        source = "network";
      } catch (error) {
        ctx.warn(`network observation unavailable: ${error.message}`);
      }
    }
    if (!entries.length) ctx.warn("no danmaku found in the snapshot or observation window");

    ctx.capture({
      playbook: NAME,
      url: meta.url || url,
      metadata: {
        bvid: meta.bvid || bvidFrom(url),
        title: meta.title,
        site: "bilibili",
        source,
        experimental: true,
        count: entries.length,
      },
      markdown: entries.length
        ? entries.map((entry) => `- ${entry.time || ""} ${entry.text}`.trim()).join("\n")
        : "No danmaku captured.",
      tables: [
        {
          name: "danmaku",
          columns: ["time", "text"],
          rows: entries.map((entry) => [entry.time || "", entry.text || ""]),
        },
      ],
      warnings: [],
    });

    return {
      summary: { captured: 1, danmaku: entries.length, source, experimental: true },
    };
  },
};
