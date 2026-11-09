"use strict";

const { ActorError } = require("../lib/errors");
const { openAndCapture } = require("./shared");
const { bvidFrom } = require("../lib/snapshot");
const { BILIBILI } = require("../lib/selectors");

const NAME = "bili-video";

module.exports = {
  name: NAME,
  description: "Open one Bilibili video, read the player state, scroll the visible comments, and capture the page.",
  requires: ["url"],

  async run(ctx) {
    let url = ctx.options.url;
    if (!url && ctx.options.bvid) url = `${BILIBILI.homeUrl}video/${ctx.options.bvid}`;
    if (!url) throw new ActorError("argument", "bili-video needs --url or --bvid");

    const result = await openAndCapture(ctx, url, {
      commentScrolls: Number(ctx.options.commentScrolls === undefined ? 3 : ctx.options.commentScrolls),
      playbook: NAME,
    });
    const bvid = result.meta.bvid || bvidFrom(url);
    const status = bvid && result.comments.length ? "ok" : "degraded";

    return {
      summary: {
        captured: 1,
        bvid,
        title: result.meta.title,
        comments: result.comments.length,
        status,
        reason: status === "ok" ? "" : bvid ? "no visible comments" : "no BV id found on the page",
      },
    };
  },
};
