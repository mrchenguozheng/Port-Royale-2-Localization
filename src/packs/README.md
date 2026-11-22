# 语言包元数据

每个语言一份：

```
src/packs/<代码>.toml
```

字段：

```toml
alias = "简体中文"   # GUI 列表里的显示名
min_runtime = 1      # 最低运行时版本
# version = "1.0.0"  # 可选：发行版本；出包时由 --version 注入，一般不手写
```

`version` 只在发行时确定：`release.ps1 -Version v1.0.0` 会把它传给
`make_release.py` → `compile_pack.py --version`，写进 pack 头。开发构建不传，
pack 头就没有这一行，启动器列表只显示名字。写进头的值不带前缀 `v`
（`version=1.0.0`），显示时补成 `v1.0.0`。

以下字段可选，只用于发行清单和审计，不会写进语言包 `# pack-meta`，运行时也不读取：

```toml
tags = ["fan", "community", "ai-assist"]  # 必填：是谁做的、怎么做的（词表见 src/tools/pack/pack_tags.py）
review_status = "preview"                 # 完成度：preview / complete
source_lang = "en.gog_1.1.2.3"            # 参考原文，对应 src/orig/<source_lang>.toml
```

`tags` 的可用值由 `pack_tags.py` 固定，`config_check.py` 拒绝表外标记：

| 标记 | 含义 |
|---|---|
| `official` | 官方本地化 |
| `retail` | 随零售版附带的官方本地化 |
| `fan` | 同人制作，非官方 |
| `community` | 社区协作，接受外部贡献 |
| `ai-assist` | AI 辅助起草，有人工审校环节 |
| `machine` | 纯机器翻译，未经人工校对 |

我们自己的译文一律 `["fan", "community", "ai-assist"]`；早期写的
`origin`/`ai_assisted` 已废弃，`config_check.py` 遇到会直接报错。

`compile_pack.py` 把 `alias`、`min_runtime`（发行构建再加 `version`）写成语言包开头的注释：

```
# pack-meta alias=简体中文
# pack-meta min_runtime=1
# pack-meta version=1.0.0        ← 只有发行包有
0x... = ...
```

游戏的语言包解析器会跳过 `#` 开头的行，所以不影响游戏。
GUI 读取这些注释后：

- 列表显示 `alias` 与版本，如 `简体中文 · v1.0.0`；没有版本时只显示名字；
- 状态框重复一遍当前选中的包（`3 个语言包 · 当前 简体中文 · v1.0.0`）；
- `min_runtime` 高于当前运行时版本时拒绝启动。

启动器界面不再跟随语言包：固定读 `PR2Localization/ui/ui.default.ini`，用户可在同目录放
`ui.ini` 按项覆盖。语言包只负责游戏内文本，不再带 `gui`。

也可以直接改已生成的 `PR2Localization/packs/<代码>.txt` 开头来覆盖（手改后重新编译会被
`src/packs/<代码>.toml` 覆盖）。
