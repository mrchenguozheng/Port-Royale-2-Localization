# 语言包元数据

每个语言一份：

```
src/packs/<代码>.toml
```

字段：

```toml
alias = "简体中文"   # GUI 列表里的显示名
gui = "zh"           # 用哪份 ui/<gui>.ini 当 GUI 界面语言
min_runtime = 1      # 最低运行时版本
```

以下字段可选，只用于发行清单和审计，不会写进语言包 `# pack-meta`，运行时也不读取：

```toml
origin = "community"             # community / retail / official / unspecified
ai_assisted = true               # 是否使用 AI 辅助翻译
review_status = "preview"        # preview / complete / ...
source_lang = "en.gog_1.1.2.3"   # 参考原文，对应 src/orig/<source_lang>.toml
```

`compile_pack.py` 只把 `alias`、`gui`、`min_runtime` 写成语言包开头的注释：

```
# pack-meta alias=简体中文
# pack-meta gui=zh
# pack-meta min_runtime=1
0x... = ...
```

游戏的语言包解析器会跳过 `#` 开头的行，所以不影响游戏。
GUI 读取这些注释后：

- 列表显示 `alias` 而不是语言代码；
- 切换到该语言包时，界面文字换成 `gui` 对应语言；
- `min_runtime` 高于当前运行时版本时拒绝启动。

也可以直接改已生成的 `PR2Localization/packs/<代码>.txt` 开头来覆盖（手改后重新编译会被
`src/packs/<代码>.toml` 覆盖）。
