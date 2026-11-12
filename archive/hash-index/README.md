# hash 用途索引（已归档）

这份东西是 2026-10-20 做的一版「每条字符串是干什么用的」索引，用来快速定位
3500 多个 hash。**后续流程不再使用它**，原样留在这里备查。

## 内容

| 文件 | 说明 |
|---|---|
| `hash_index.py` | 生成脚本（原在 `src\tools\`，已移到这里） |
| `hash-index.md` | 生成结果：按 hash 顺序，一条一行，`作用 / 段落数 / 占位符数` |
| `hash-index.csv` | 同上，CSV 版（Excel 直接打开） |

「作用」是按英文/法文原文的结构与关键词判定的，形如 `船队·角色对白/叙述`、
`标签：木材`、`术语·城镇：哈瓦那`；**只概括用途，不抄原文**。

## 为什么归档

它解决的是「这个 hash 大概是干嘛的」这类临时问题。现在有更直接的办法：
编辑器里搜索原文片段、术语对照表、以及 `translate.py` 的校验，都不需要先
翻这份索引。留在 `src\tools\` 里反而会让人以为流程依赖它。

## 如果以后还要用

```bat
python archive\hash-index\hash_index.py                 # 用中文摘要
python archive\hash-index\hash_index.py --lang ja       # 用日语摘要
```

输出会写到 `build\hash-index.md` / `.csv`（覆盖旧的生成物）。脚本依赖
`src\tools\translate.py` 与 `glossary.py`，所以它们还在原处。
