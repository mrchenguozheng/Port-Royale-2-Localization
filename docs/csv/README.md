# CSV 数据索引

CSV 是分析和人工审校的附属数据，不是游戏运行需要的文件。
按用途分目录，`docs/` 根目录只放说明文档。

## analysis/：分析结果

| 文件 | 生成方式 | 用途 |
|---|---|---|
| `analysis/宽度粗查-zh.csv` / `-ja.csv` | `python src/tools/analysis/width_check.py --lang zh` | 译文相对英文的宽度估算；[翻译局限](../翻译局限.md) 引用 |
| `analysis/speaker-audit.csv` | `python src/tools/analysis/speaker_audit.py` | 逐条说话人/语气分级；[说话人分级](../说话人分级.md) 引用 |
| `analysis/tone-proposal.csv` | `python src/tools/analysis/tone_proposal.py` | 语体建议；[语体拟改清单](../语体拟改清单.md) 引用 |
| `analysis/占位符语义.zh.csv` / `.ja.csv` | `python src/tools/placeholder_roles.py --report --lang zh` | 相邻 `%N %N` 的连接符建议；[译文与语言包](../译文与语言包.md) 引用 |

## voice/：语音

| 文件 | 生成方式 | 用途 |
|---|---|---|
| `voice/voice-inventory.csv` | 由语音文件 `ffprobe` 统计 | 语音文件清单；[语音清单](../语音清单.md) 引用 |
| `voice/voice-hash-map.csv` | `python src/tools/voice_match.py` | 语音与文本 hash 的映射；[语音映射](../语音映射.md) 引用 |

## review/：人工审校

| 文件 | 说明 |
|---|---|
| `review/人工修订.csv` | 人工确认过的中文修订记录（hash / 原译 / 改为 / 日期） |
| `review/zh-text-edits.csv` | 中文文本历史改动对照；[中文文本改动对比](../中文文本改动对比.md) 引用 |

## generated/：可重跑的中间产物

| 文件 | 生成方式 | 说明 |
|---|---|---|
| `generated/space-words-zh.csv` | `python src/tools/text/space_words.py --lang zh --dry-run` | 中文补空格的 before/after；[中文分词方案](../中文分词方案.md) 引用 |
| `generated/zh-dep-space.csv` | `python src/tools/text/zh_dep_space.py`（可选） | 依存句法补空格试验输出 |
| `generated/space-conj-dryrun.csv` | 历史 dry-run | 早期依存句法试验，仅保留作对照 |
| `generated/space-name-dryrun.csv` | 历史 dry-run | 早期专名补空格试验，仅保留作对照 |

## 不在这里的 CSV

- `build/glossary/zh.csv`：术语对照的构建产物，可重新生成；
- `build/hash-index.csv`、`archive/hash-index/hash-index.csv`：hash 索引，属于产物/归档；
- `src/**/*.csv`：测试或第三方数据。

新增分析脚本时，默认输出到对应的 `docs/csv/<类别>/`，不要放回 `docs/` 根目录。
