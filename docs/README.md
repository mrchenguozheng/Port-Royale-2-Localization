# 文档索引

[项目 README](../README.md) · [维护指南](../AGENTS.md) · [English](../README.en.md)

> **GOG 英文版 `1.1.2.3` 已实测；Steam 英文版 `1.1.2.3` 已通过宿主 DLL 代理实测。**
> GOG 正式入口是 `PR2LocalizationGUI.exe`，不要直接双击 `PR2.exe`；Steam 用
> `Ascaron.Logging-2.6.dll` + `PR2HostMount.ps1`，不再使用 `VERSION.dll`。

文档只维护中文一套。英文入口只有根目录 [README.en.md](../README.en.md)，不镜像完整文档。

## 当前契约

- 发行口径统一在[发行规范](发行规范.md)：版本号 `vMAJOR.MINOR.PATCH[-pre]`，
  语言全集读 `src/release-languages.txt`，打包分组读 `src/release-bundles.toml`
  （同一份字体能共用的语言进一个 zip），`dist/` 只留 zip 与 `SHA256SUMS.txt`。
- 发行包按分组各出一个 zip，一个包同时面向 GOG / Steam，GOG 不带 `VERSION.dll`；
  包里的 `packs/<语言>.txt` 是**同一份并集包**（GOG 由启动器注入、Steam 由宿主 DLL 代理，
  两条路径读同一个文件）。
- 语言：包内只放 `packs/locale.default.ini`；用户活动 `locale.ini` 存在时优先，
  空值也保留；部署/升级不覆盖，`packs/overrides/` 不删除。
  运行时把空值当「回到内置 `zh`」，不等于原版英文；原版入口是
  `PR2Localization.exe --vanilla` 或 GUI「启动原版」。
- 语言包元数据：`<语言>.txt` 开头的 `# pack-meta alias=…` / `min_runtime=…`，
  发行包再加 `version=…` 与编译期算出的 `entries` / `untranslated` / `scope` / `digest`。
- 字体：实际字体平铺在 `PR2Localization/fonts/`；包内放 `font-map.default.ini`，
  用户 `font-map.ini` 按项覆盖默认；不按语言开子目录，不覆盖根目录原版字体；
  只认 fonts 里的文件，不读系统字体目录。
- 启动器界面：固定 `PR2Localization/ui/ui.default.ini`；用户 `ui.ini` 按项覆盖。
- 运行时版本：`src/injector-rs/pr2_common/src/lib.rs`；发行包根目录 `RUNTIME-VERSION`。

旧的 `launcher.ini`、`lang/aliases.ini` 已移除；旧语言包不再兼容。

## 玩家

| 文档 | 内容 |
|---|---|
| [玩家指南](玩家指南.md) | 下载、解压、启动、切换语言、卸载、常见问题 |

## 构建与发行

| 文档 | 内容 |
|---|---|
| [构建与安装](构建与安装.md) | 构建、部署、启动、脚本一览 |
| [发行规范](发行规范.md) | 版本号、发行语言集、产物与校验和、tag、门禁 |
| [发行版](发行版.md) | 两个发行包的结构、字体、语言设置、GitHub Actions |
| [发行构建计划](archive/发行构建计划.md) | 发行包构建的分步计划与验收项 |
| [字体与分发](字体与分发.md) | 字体只做映射、Noto 许可、`font-map` 映射、禁止分发 |
| [新语言](新语言.md) | 从准备字体到翻译、构建、部署、验收、出包 |

## 开发与原理

| 文档 | 内容 |
|---|---|
| [架构与重构](架构与重构.md) | 分层、文件契约、当前边界、已知问题 |
| [注入组件](注入组件.md) | DLL 如何 hook 取字、启动器如何注入 |
| [译文与语言包](译文与语言包.md) | 语言包格式、`hash = 译文`、TOML 编辑流程 |
| [流水线](流水线.md) | 参照层 → 译文层 → 校验层 → 出包层：每段的入口、产物与顺序约束 |
| [文本变量码表](文本变量码表.md) | `@码$变量名$` 的 19 个码、67 个变量名、三档置信度与查询工具 |
| [语言规则接口](语言规则接口.md) | 标点 / 分词 / 补空格三段式；中文补空格细节 |
| [开发依赖](开发依赖.md) | Python、fontTools、Rust 等 |
| [翻译局限](翻译局限.md) | 哪些文本改不了、排版为什么只能实机看 |

## 界面映射

| 文档 | 内容 |
|---|---|
| [界面映射/README.md](界面映射/README.md) | 「哪句话出现在哪个界面」的十二卷总览：分卷表、排查包标记清理规则、待采集清单 |
| [01 菜单与剧本](界面映射/01-菜单与剧本.md) … [12 内部贴图资源名索引](界面映射/12-内部贴图资源名索引.md) | 按界面分卷，每卷一张「界面 → 键」表，语言列只作对照；卷名与内容见子索引 |

## 翻译数据与历史

| 文档 | 内容 |
|---|---|
| [说话人分级](说话人分级.md) | 角色语气分级 |
| [语音与映射](语音与映射.md) | 语音文件清单、语音 ↔ hash ↔ NPC 映射 |
| [待定](待定.md) | 尚未完成或未验证的方向 |
| [历史重构记录](历史重构记录.md) | 已完成的阶段重构、旧路由变化和 C++ 迁移对照 |
| [历史归档](archive/README.md) | 各语言批次审计、一次性报告与已落地计划（只读） |

## CSV 数据

分析、审校、语音等数据统一放在 [csv/](csv/README.md)，不混在文档根目录。
