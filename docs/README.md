# 文档索引

[项目 README](../README.md) · [维护指南](../AGENTS.md) · [English](../README.en.md)

> **GOG 英文版 `1.1.2.3` 已实测；Steam 英文版 `1.1.2.3` 已通过宿主 DLL 代理实测。**
> GOG 正式入口是 `PR2LocalizationGUI.exe`，不要直接双击 `PR2.exe`；Steam 用
> `Ascaron.Logging-2.6.dll` + `PR2HostMount.ps1`，不再使用 `VERSION.dll`。

文档只维护中文一套。英文入口只有根目录 [README.en.md](../README.en.md)，不镜像完整文档。

## 当前状态

- 发行包按 GOG / Steam 分成两个；GOG 不带 `VERSION.dll`。
- 语言：包内只放 `packs/locale.default.ini`；用户活动 `locale.ini` 存在时优先，
  空值也保留；部署/升级不覆盖，`packs/overrides/` 不删除。
- 字体：实际字体平铺在 `PR2Localization/fonts/`；包内放 `font-map.default.ini`，
  用户 `font-map.ini` 按项覆盖默认；不按语言开子目录，不覆盖根目录原版字体。
- 运行时空值不表示“原版英文”：空值只会回到内置 `zh`；原版入口是
  `PR2Localization.exe --vanilla` 或 GUI「启动原版」。

## 玩家

| 文档 | 内容 |
|---|---|
| [玩家指南](玩家指南.md) | 下载、解压、启动、切换语言、卸载、常见问题 |

## 构建与发行

| 文档 | 内容 |
|---|---|
| [构建与安装](构建与安装.md) | 安装页按钮、构建、部署、启动、脚本一览 |
| [发行版](发行版.md) | 两个发行包的结构、字体、语言设置、GitHub Actions |
| [字体与分发](字体与分发.md) | Noto / 缝合字体许可、`font-map` 映射、禁止分发 |
| [新语言](新语言.md) | 从准备字体到翻译、构建、部署、验收、出包 |

## 开发与原理

| 文档 | 内容 |
|---|---|
| [架构与重构](架构与重构.md) | 分层、文件契约、当前边界、已知问题 |
| [注入组件](注入组件.md) | DLL 如何 hook 取字、启动器如何注入 |
| [译文与语言包](译文与语言包.md) | 语言包格式、`hash = 译文`、编辑器工作流 |
| [语言规则接口](语言规则接口.md) | 标点 / 分词 / 补空格三段式；中文补空格细节 |
| [编辑器接口契约](agent-api.md) | agent 读写译文、校验、构建/部署的 HTTP 路由 |
| [开发依赖](开发依赖.md) | Python、fontTools、Rust 等 |
| [翻译局限](翻译局限.md) | 哪些文本改不了、排版为什么只能实机看 |

## 翻译数据与历史

| 文档 | 内容 |
|---|---|
| [说话人分级](说话人分级.md) | 角色语气分级 |
| [语体拟改清单](语体拟改清单.md) | 待统一语体的条目 |
| [语音与映射](语音与映射.md) | 语音文件清单、语音 ↔ hash ↔ NPC 映射 |
| [中文文本改动对比](中文文本改动对比.md) | 历史改字台账 |
| [待定](待定.md) | 尚未完成或未验证的方向 |
| [历史重构记录](历史重构记录.md) | 已完成的阶段重构、旧路由变化和 C++ 迁移对照 |

## CSV 数据

分析、审校、语音等数据统一放在 [csv/](csv/README.md)，不混在文档根目录。

## 当前契约

- 游戏语言：`PR2Localization/packs/locale.default.ini` 是发行默认；用户
  `locale.ini` 存在时优先，空值也保留。
- 语言包元数据：`<语言>.txt` 开头的 `# pack-meta alias=…` / `gui=…` /
  `min_runtime=…`。
- 字体：`PR2Localization/fonts/` 放实际字体和默认映射 `font-map.default.ini`；
  用户 `font-map.ini` 按项覆盖默认；实际字体必须位于该目录，不读系统字体目录。
- 启动器界面翻译：`PR2Localization/ui/<语言>.ini`。
- 运行时版本：`src/injector-rs/pr2_common/src/lib.rs`；发行包根目录 `RUNTIME-VERSION`。

旧的 `launcher.ini`、`lang/aliases.ini` 已移除；旧语言包不再兼容。
