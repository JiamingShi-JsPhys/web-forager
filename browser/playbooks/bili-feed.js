"use strict";

const { guardedGoto, guardedScroll } = require("../lib/safety");
const { findVideoCards } = require("../lib/snapshot");
const { hasCaptured, markCaptured, markVisited } = require("../lib/session");

const NAME = "bili-feed";

module.exports = {
  name: NAME,
  description: "Open the Bilibili home feed, scroll screen by screen, and capture each unseen video card.",
  requires: [],

  async run(ctx) {
    const url = ctx.options.url || "https://www.bilibili.com/";
    const maxItems = Number(ctx.options.maxItems || 10);
    const maxScreens = Number(ctx.options.maxScreens || 3);

    await guardedGoto(ctx, url);
    markVisited(ctx.session, url);

    let captured = 0;
    let screens = 0;
    for (let screen = 0; screen < maxScreens && captured < maxItems; screen += 1) {
      const snapshot = await ctx.backend.snapshot();
      screens += 1;
      for (const card of findVideoCards(snapshot)) {
        if (captured >= maxItems) break;
        if (hasCaptured(ctx.session, card.bvid)) continue;
        ctx.capture({
          playbook: NAME,
          url: card.url,
          metadata: { bvid: card.bvid, title: card.title },
          markdown: `- ${card.title}\n- ${card.url}`,
        });
        markCaptured(ctx.session, {
          id: card.bvid,
          url: card.url,
          title: card.title,
          playbook: NAME,
        });
        captured += 1;
      }
      if (screen + 1 < maxScreens && captured < maxItems) await guardedScroll(ctx, 900);
    }

    return { summary: { captured, screens, max_items: maxItems } };
  },
};
