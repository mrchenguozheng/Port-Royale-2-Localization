# 语言包元数据

每个语言一份：

```
src/packs/<代码>.toml
```

字段：

```toml
alias = "简体中文"   # GUI 列表里的显示名
gui = "zh"           # 用哪份 ui/<gui>.ini 当 GUI 界面语言
```

`compile_pack.py` 会把它们写成语言包开头的注释：

```
# pack-meta alias=简体中文
# pack-meta gui=zh
0x... = ...
```

游戏的语言包解析器会跳过 `#` 开头的行，所以不影响游戏。
GUI 读取这些注释后：

- 列表显示 `alias` 而不是语言代码；
- 切换到该语言包时，界面文字换成 `gui` 对应语言。

也可以直接改已生成的 `PR2Packs/<代码>.txt` 开头来覆盖（手改后重新编译会被
`src/packs/<代码>.toml` 覆盖）。
