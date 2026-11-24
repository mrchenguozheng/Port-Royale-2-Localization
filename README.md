# Port Royale 2 本地化

《Port Royale 2》的本地化项目：**用外挂语言包替换界面文本，原版 `PR2.exe` 全程不改。**

[实机截图（十二种语言）](https://mrchenguozheng.github.io/Port-Royale-2-Localization/) · [English](README.en.md) · [中文文档索引](docs/README.md)

**Supported languages:** Simplified Chinese (`zh`), Traditional Chinese — Taiwan (`zh-TW`), Traditional Chinese — Hong Kong (`zh-HK`), Japanese (`ja`), Korean (`ko`), Russian (`ru`), German (`de`), Spanish (`es`), French (`fr`), Italian (`it`), Polish (`pl`), Brazilian Portuguese (`pt-BR`); English (`en`) is the original game language and fallback. See [README.en.md](README.en.md#supported-languages).

**译文标记：** 同人制作 · 社区协作 · AI 辅助（预览版）。这批译文不是官方本地化，
由社区制作、AI 辅助起草并人工审校；旧语言包若改自原版零售文件会单独标 `retail`。
标记写在 `src/packs/<语言>.toml` 的 `tags` 里，词表见
[`pack_tags.py`](src/tools/pack/pack_tags.py)，出包时进 `README.txt` 与 `manifest.json`。

**界面译文没有母语审校。** 启动器的十二种界面文案（`zh/zh-TW/zh-HK/ja/ko/ru/pl/pt-BR/de/es/fr/it`）由 AI
起草，只做了 key 与占位符的机械一致性校验，**没有经过母语者逐句校对**。这是当前
已知短板，不是“已修复”。如果你是其中某门语言的母语玩家，愿意帮忙校对，请在项目的
Issue 区贴出「界面截图 + 现在这行文案 + 建议改法」；游戏内语言包的同类问题也欢迎一并指出。
支持范围和启动器界面选择见[运行契约](docs/运行契约.md)。

---

## 快速开始（玩家）

不需要安装器、不需要 Python、不需要编译。

挂载与还原都在启动器进程里完成（`pr2_common` 里的 Rust 实现），不调用 PowerShell，
也不受「禁止执行脚本」这类组策略影响；失败原因写在 `PR2Localization\logs\host.log`。

1. 确认系统是 **Windows 10 / Windows 11**，游戏是 GOG 英文 `1.1.2.3`、Steam 英文 `1.1.2.3`
   或 GOG 法语 `1.1.2.42`（其他版本不在验证范围）；
2. 从 Release 下载对应语言的 zip，**全部解压到 `PR2.exe` 所在的游戏根目录**——
   一个包 GOG 与 Steam 通用，例如中文是 `PR2-zh-v1.0.0.zip`；
3. **双击 `PR2LocalizationGUI.exe`**，选语言后点「以所选语言启动」：GOG 由启动器挂载宿主 DLL
   后直启游戏，Steam 挂载后交给客户端（`steam://rungameid/12470`）；
4. 进游戏后看 `PR2Localization\logs\runtime.log`，首行应有
   `pack 'zh' ... N entries, M overrides`；想回原版点 GUI「还原原版」或
   `PR2Localization.exe --restore`。

版本在 GUI 副标题、语言列表和 `PR2Localization.exe --version` 三处同源；
具体校验、卸载与常见问题见[玩家指南](docs/玩家指南.md)。

GOG 与 Steam 的 `PR2.exe` 静态导入同一份 `Ascaron.Logging-2.6.dll`，所以本地化入口只有一条；
差别只是 GOG 由启动器直启、Steam 交给客户端。包内代理放在 `PR2Localization\host\`，
启动前由启动器校验原版、备份后换入，失败即停并写 `PR2Localization\logs\host.log`；
发行包不带任何 `.ps1`。挂载后直接双击 `PR2.exe` 也有效，没挂载时双击就是原版英文。
完整校验与备份规则见[运行契约](docs/运行契约.md)。

启动器界面跟随下拉框选中的语言包：选 `Polski` 就是波兰语界面，换回简体中文即中文界面。
包内带全部 `ui.<lang>.ini`，`ui.default.ini` 只作兜底；源码十二份，构建时由 `ui.zh.ini` 生成默认文件。
包内布局、挂载语义与支持环境见[运行契约](docs/运行契约.md)。

注意：

- 不要删除 `fonts\` 根目录的四份原版字体；
- 缺字体时 GUI 会提示，把 zip 里的 `PR2Localization\fonts\` 重新解压完整即可；
  发行包默认把 Noto 实际字体文件（保留原始文件名）平铺进 `PR2Localization\fonts\`，
  同时附带 `font-map.default.ini`，由它映射游戏的四个逻辑字体名；
  要自定义时新建或编辑同目录的 `font-map.ini`，只写需要覆盖的逻辑名（运行时在默认映射上按项叠加），解压升级不会覆盖它；
  也可用 `-Fonts config` 只带 `PR2Localization\fonts\font-map.default.ini`，此时必须自己把
  映射中写明的实际字体文件放进 `fonts`；映射不读取系统字体目录；
  非拉丁系默认使用 Noto 对应字体，只接受静态字重，不使用 `.ttc` 或 `-VF.ttf`。

完整步骤、卸载和常见问题见[玩家指南](docs/玩家指南.md)。

---

## 支持范围

**本项目用于给原版游戏套其他语言包；原版 `PR2.exe` 不改。** 语言包的键是条目 id，
英文版与 GOG 法语版共用同一套 id，所以同一个包在两版里都能命中。

| 项目 | 状态 |
|---|---|
| **Windows 10 / Windows 11** | ✅ 支持（64 位系统跑 32 位游戏） |
| Windows 7 | ❌ 不支持，也没有验证过 |
| **GOG 英文 `1.1.2.3`** | ✅ 已实测（宿主 `Ascaron.Logging-2.6.dll` 代理，中文界面） |
| **Steam 英文 `1.1.2.3`** | ✅ 已实测（同上，启动交给 Steam 客户端） |
| **GOG 法语 `1.1.2.42`** | ✅ 已实测（2026-11-22，pl 包；宿主代理生效，游戏内版本号仍是 `1.1.2.42`。该版比英文版多 42 条 `+++EMPTY+++` 空占位、少 19 条，这些条目按原样保留） |
| 其他游戏版本 | ❌ 不支持（零售版等不在验证范围） |

挂载和还原都经过 `Ascaron.Logging-2.6.dll` 的大小/SHA-256 校验，未知文件不覆盖。
未验证的版本不要反馈“汉化已支持”，先附 `PR2Localization\logs\runtime.log` 和
`PR2Localization\logs\proxy.log`。实现细节见[注入组件](docs/注入组件.md)。

---

## 文档

完整分类见[文档索引](docs/README.md)，这里只列玩家最常用的几篇：

| 文档 | 内容 |
|---|---|
| [玩家指南](docs/玩家指南.md) | 下载 zip、解压、启动、卸载、常见问题 |
| [运行契约](docs/运行契约.md) | 支持环境、包内布局、界面语言、宿主挂载的唯一口径 |
| [语言矩阵](docs/语言矩阵.md) | 每门语言的发行状态、译文、字体与发行分组；生成物 |
| [术语对照](glossary/README.md) | 货物/船只/军衔/城镇等专名的英中对照 |
| [文档索引](docs/README.md) | 全部文档与归档 |

---

## 已知限制

- **hook 目标与游戏版本绑定。** 代码按固定偏移取 `A2dLib-2.20A.dll` 的函数。
  已知的三个版本（GOG 英文 `1.1.2.3`、Steam 英文 `1.1.2.3`、GOG 法语 `1.1.2.42`）
  都用同一组偏移并已实测；换其他版本（零售版、补丁版）很可能需要改偏移，否则整体不生效。
- **中文条目整条不显示是分词问题，不是标签问题。** 引擎按空格切词，
  整串汉字超宽会被整条丢弃，只能逐条在游戏里实测。
- **字体统一放在 `PR2Localization\fonts\`。** 实际字体文件平铺，不按语言子目录；
  四个游戏逻辑名由 `font-map.ini` 映射，映射只接受 fonts 内的文件，只接受静态字重，
  不使用 `.ttc` 或 `-VF.ttf`。

---

## 语言完成度

十二门发行语言在各自“已译 / 可译”口径下均为 100%：按键名、职员表、纯符号、空占位等
“有意不译”条目不计入待译。逐语言数字、字体与发行分组见[语言矩阵](docs/语言矩阵.md)；
实时值用 `python src\tools\translate.py status --lang <代码>` 查询。

## 参与开发

开发环境、译文改动流程、构建与发版、仓库结构、新语言步骤和 PR 检查见
[CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可

见 [LICENSE](LICENSE).
