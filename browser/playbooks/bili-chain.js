"use strict";

const { ActorError } = require("../lib/errors");
const { guardedClick, guardedGoto } = require("../lib/safety");
const { findNextEpisode } = require("../lib/snapshot");
const { pushChain } = require("../lib/session");
const { captureCurrent } = require("./shared");

const NAME = "bili-chain";

module.exports = {
  name: NAME,
  description: "Follow the next-episode chain from a seed video, capturing each episode and resuming from the session.",
  requires: ["url"],

  async run(ctx) {
    const maxItems = Number(ctx.options.maxItems || 3);
    let seed = ctx.options.url;
    if (!seed && ctx.options.bvid) seed = `https://www.bilibili.com/video/${ctx.options.bvid}`;
    if (!seed) {
      const last = ctx.session.chain[ctx.session.chain.length - 1];
      if (last) seed = `https://www.bilibili.com/video/${last}`;
    }
    if (!seed) throw new ActorError("argument", "bili-chain needs --url, --bvid, or a session with a chain");

    await guardedGoto(ctx, seed);
    let captured = 0;
    let stopped = "";

    for (let step = 0; step < maxItems; step += 1) {
      const { meta, snapshot } = await captureCurrent(ctx, {
        commentScrolls: 1,
        playbook: NAME,
      });
      captured += 1;
      if (meta.bvid) pushChain(ctx.session, meta.bvid);
      if (step + 1 >= maxItems) break;

      const next = findNextEpisode(snapshot);
      if (!next) {
        stopped = "no next-episode control found";
        break;
      }
      await guardedClick(ctx, next);
    }

    return {
      summary: {
        captured,
        chain: ctx.session.chain.slice(),
        stopped: stopped || "max items reached",
      },
    };
  },
};
