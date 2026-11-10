# 致谢

这里记录报告过问题、并因此改变了这个项目的人：谁、报告了什么、改了什么。README 只列名字，细节放在这一页。

[English](ACKNOWLEDGEMENTS.md) · **简体中文**

## NotFatJustRound

[issue #1](https://github.com/JiamingShi-JsPhys/web-forager/issues/1)。

`web_search` 把每个页面的正文返回了两遍（`pages` 与 `results` 各一份），响应体积翻倍并超出智能体的大小上限。1.0.2 起新增的精简 `results` 索引、以及之后对输出体积的处理，都来自这份报告。
