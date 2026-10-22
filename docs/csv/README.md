# CSV 数据索引

CSV 是分析和人工审校的附属数据，不是游戏运行需要的文件。
`docs/` 根目录只放说明文档，数据统一放在这里。

## 分析结果

| 文件 | 生成方式 | 用途 |
|---|---|---|
| `宽度粗查-zh.csv` / `宽度粗查-ja.csv` | `python src/tools/analysis/width_check.py --lang zh` | 译文相对英文的宽度估算；[翻译局限](../翻译局限.md) 引用 |
| `speaker-audit.csv` | `python src/tools/analysis/speaker_audit.py` | 逐条说话人/语气分级；[说话人分级](../说话人分级.md) 引用 |
| `tone-proposal.csv` | `python src/tools/analysis/tone_proposal.py` | 语体建议；[语体拟改清单](../语体拟改清单.md) 引用 |
| `voice-inventory.csv` | 由语音文件 `ffprobe` 统计 | 语音文件清单；[语音清单](../语音清单.md) 引用 |
| `voice-hash-map.csv` | `python src/tools/voice_match.py` | 语音与文本 hash 的映射；[语音映射](../语音映射.md) 引用 |
| `占位符语义.zh.csv` / `.ja.csv` | `python src/tools/placeholder_roles.py --report --lang zh` | 相邻 `%N %N` 的连接符建议；[译文与语言包](../译文与语言包.md) 引用 |
| `zh-dep-space.csv` | `python src/tools/text/zh_dep_space.py`（可选） | 依存句法补空格试验输出 |
| `space-words-zh.csv` | `python src/tools/text/space_words.py --lang zh --dry-run` | 中文补空格的 before/after；[中文分词方案](../中文分词方案.md) 引用 |

## 人工审校

| 文件 | 说明 |
|---|---|
| `人工修订.csv` | 人工确认过的中文修订记录（hash / 原译 / 改为 / 日期） |
| `zh-text-edits.csv` | 中文文本历史改动对照；[中文文本改动对比](../中文文本改动对比.md) 引用 |

## 历史 dry-run

| 文件 | 说明 |
|---|---|
| `space-conj-dryrun.csv` | 早期依存句法补空格试验输出，仅保留作对照 |
| `space-name-dryrun.csv` | 早期专名补空格试验输出，仅保留作对照 |

## 不在这里的 CSV

- `build/glossary/zh.csv`：术语对照的构建产物，可重新生成；
- `build/hash-index.csv`、`archive/hash-index/hash-index.csv`：hash 索引，属于产物/归档；
- `src/**/*.csv`：测试或第三方数据。

新增分析脚本时，默认输出到 `docs/csv/`，不要放回 `docs/` 根目录。
