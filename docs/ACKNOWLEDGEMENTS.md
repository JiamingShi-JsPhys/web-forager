# Acknowledgements

People who reported a problem that changed this project, with what they reported and what it changed. The README carries the names; this page carries the detail.

**English** · [简体中文](ACKNOWLEDGEMENTS_zh.md)

## NotFatJustRound

[issue #1](https://github.com/JiamingShi-JsPhys/web-forager/issues/1).

`web_search` returned every page body twice, once in `pages` and once in `results`. That doubled every response and pushed the tail past an agent's size limit. The compact `results` index added in 1.0.2, and the size-aware envelopes since then, came from this report.
