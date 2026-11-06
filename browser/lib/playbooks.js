"use strict";

const playbooks = {
  "bili-feed": require("../playbooks/bili-feed"),
  "bili-video": require("../playbooks/bili-video"),
  "bili-chain": require("../playbooks/bili-chain"),
  "bili-danmaku": require("../playbooks/bili-danmaku"),
  "zhihu-dig": require("../playbooks/zhihu-dig"),
  "xhs-dig": require("../playbooks/xhs-dig"),
  "search-dig": require("../playbooks/search-dig"),
};

function getPlaybook(name) {
  const playbook = playbooks[name];
  if (!playbook) {
    throw new Error(`unknown playbook: ${name}. Known: ${Object.keys(playbooks).join(", ")}`);
  }
  return playbook;
}

function listPlaybooks() {
  return Object.values(playbooks).map((playbook) => ({
    name: playbook.name,
    description: playbook.description,
    requires: playbook.requires,
  }));
}

module.exports = { playbooks, getPlaybook, listPlaybooks };
