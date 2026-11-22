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

`compile_pack.py` 把 `alias`、`min_runtime`（发行构建再加 `version`）写成语言包开头的注释，
后面再跟四行由编译过程自己算出来的内容描述：

```
# pack-meta alias=简体中文
# pack-meta min_runtime=1
# pack-meta version=1.0.0        ← 只有发行包有
# pack-meta entries=3590         ← 包里的数据行总数
# pack-meta untranslated=0       ← 占位未翻译的条目数（原文本来就空的键不算）
# pack-meta scope=union          ← 键集来源：union（GOG/Steam 合包）
# pack-meta digest=9cfa2931c1c2  ← 正文内容的 sha256 前 12 位，不含上面这些头
0x... = ...
```

`entries` / `untranslated` / `scope` / `digest` 都不需要手写，也不受 `--version` 影响：
摘要**只算正文**，同一份译文换个版本号重打包，摘要不变；`scope` 区分「并集键集」
与单版键集，正文一样时两者仍会给出不同摘要 —— 这是对的，并集比单版多了别版独有的键。

游戏的语言包解析器会跳过 `#` 开头的行，所以不影响游戏。
GUI 读取这些注释后：

- 列表显示 `alias` 与版本，如 `简体中文 · v1.0.0`；没有版本时只显示名字；
- 状态框第一行重复当前选中的包（`3 个语言包 · 当前 简体中文 · v1.0.0`），
  第二行显示内容（`3590 条 · 未译 0 · 摘要 9cfa2931c1c2`）；旧包没有 `entries`
  时只显示第一行，不会显示成「0 条」；
- `overrides\<语言>.txt` 是本机覆盖位：同 hash 条目覆盖包里的译文，**不进包**、
  不改包头，界面也不统计；发行包只带一个空的 `overrides\` 目录；
- `min_runtime` 高于当前运行时版本时拒绝启动。

摘要的用处是**判断两份包是不是同一份内容**：手上那份和刚下的那份摘要一样，
说明译文逐字相同；不一样但版本号相同，说明是同一版本重打的包，译文动过。
回答不了「改了哪几条」—— 那要靠出包时写在 `README.txt` 与 `manifest.json`
里的 `delta`（相对上一个 `release-v*` tag 的条目增改删）。

启动器界面随发包语言走：源目录只有按语言的 `ui.<lang>.ini` 九份，**没有 `ui.default.ini`**
（构建时从 `ui.zh.ini` 生成运行时默认）；发行包把分组默认语言那份复制成
`PR2Localization/ui/ui.default.ini`；用户可在同目录放 `ui.ini` 按项覆盖。
语言包只负责游戏内文本，不带 `gui`。

也可以直接改已生成的 `PR2Localization/packs/<代码>.txt` 开头来覆盖（手改后重新编译会被
`src/packs/<代码>.toml` 覆盖）。
