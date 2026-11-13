# AGENTS.md — 项目维护指南

> 面向接手本仓库的 agent。先读本页，再读 [文档索引](docs/README.md) 和
> [当前架构与文件契约](docs/架构与重构.md)。本页只写维护规则和验证入口，不重复全部
> 玩家文档。

## 项目边界

- 这是《Port Royale 2》的**外挂式本地化运行时**：原版 `PR2.exe` 不改字节。
  GOG 的正式入口是 `PR2LocalizationGUI.exe` / `PR2Localization.exe`，由启动器注入
  `PR2LocalizationCore.dll`。不要按“GOG 双击 `PR2.exe` 自然加载”做回归：GOG 加载器会把
  `VERSION.dll` 解析到 `C:\Windows\SysWOW64\VERSION.dll`，同目录代理不会进入
  `PR2.exe` 进程。Steam 的实验性自然加载路径才使用 `VERSION.dll` 代理。
- **GOG 英文版 `1.1.2.3` 已通过启动器入口实测；Steam 英文版为实验性支持**。
  GOG 法语版和其他版本不在支持范围内；不要在未支持版本上部署后把“注入不生效”
  当作本仓库回归。
- 发行包按语言和入口拆分：GOG 版不带 `VERSION.dll`，Steam 版带 `VERSION.dll`；
  两版都包含 `PR2LocalizationCore.dll`、语言包和字体，不需要 Python 或 Rust 工具链。
  不要把“让每个玩家自行构建”写成默认流程。

## 当前结构

| 路径 | 作用 |
|---|---|
| `src/injector-rs/` | Rust workspace：`pr2_common`、`pr2_proxy`、`pr2_text_source`、`pr2_launcher`、`pr2_launcher_gui` |
| `src/injector-rs/ui/` | GUI 界面翻译 `zh.ini` / `en.ini` / `ja.ini` |
| `src/translations/` | 唯一手改译文层：`zh.toml`、`ja.toml` 等 |
| `src/editor/` | 最小译文编辑器：Astro 前端 + `server.py` + `api/` 分域模块 |
| `src/tools/` | 语言包编译、字体、部署、校验和分析工具 |
| `build/` | 构建产物；`build/runtime/` 是可整体复制的安装源 |
| `docs/` | 维护文档；当前架构与历史重构记录已分开 |
| `tests/` | Python 规则/API 测试与 Rust 测试 |

Rust 产物：

- `PR2LocalizationProxy.dll`（构建产物；部署时必须改名为 `VERSION.dll`）
- `VERSION.dll`
- `PR2LocalizationCore.dll`
- `PR2Localization.exe`
- `PR2LocalizationGUI.exe`

`VERSION.dll` 是代理宿主，不是游戏原文件；它必须和 `PR2LocalizationCore.dll` 同目录。
不要用裸 `LoadLibraryExW("version.dll")` 找系统 DLL，可能递归到代理自身；
用 `GetSystemDirectoryW` 拼绝对路径。

## 不可破坏的契约

- `src/translations/<语言>.toml` 是**唯一手改层**；不要直接改 `build/` 下的产物。
- 运行时语言包是 `PR2Localization/packs/<语言>.txt`，格式为 `0x... = text` 一行一条；不要把旧的
  `|` 换行兜底重新加回来。需要换行时用引擎标签/已有规则，不要自行发明格式。
- `PR2Localization/packs/locale.ini` 的 `language=` 是游戏默认语言，也是 GUI 的唯一语言状态。
- `PR2Localization/fonts/<语言>/` 固定四个 TTF；不要覆盖游戏根目录 `fonts/` 的原版字体。
- 译文里的 hash id、`%1` 等占位符、`@D$...$` 脚本变量、`<n>`、`<c>`、`<f:...>` 标签
  都不是可翻译文本；改译文时保持原样。
- 字体路径、语言包路径和 GUI 文案的详细规则见
  [文件契约](docs/架构与重构.md#文件契约) 与 [译文与语言包](docs/译文与语言包.md)。

## 常用入口

所有脚本都要求 **PowerShell 7（pwsh）**，在仓库根目录执行：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

启动本地工作台，打开安装/译文编辑页；它**不会自动编译**。

```powershell
.\build.ps1                         # 注入器 + 全部语言包（zh、ja）
.\build.ps1 -Target Packs -Lang zh  # 只编中文语言包
.\build.ps1 -Target Injector        # 只编 Rust 注入器

.\release.ps1 -Version v1.0.0       # 同时生成 gog/steam 两套 zip
.\release.ps1 -Version v1.0.0 -Edition gog    # 只出 GOG 包
.\release.ps1 -Version v1.0.0 -Edition steam  # 只出 Steam 包
.\release.ps1 -Version v1.0.0 -Tag -Push  # 出包并创建/推送 release-<版本> tag
```

日常入口在仓库根目录；`src\build_injector.ps1`、`src\build_translation.ps1`
仍是低层实现，排查单步问题时才直接调用。

```powershell
.\apply_patch.ps1
.\apply_patch.ps1 --langs ja
.\apply_patch.ps1 --launch
```

归一化 → 校验 → 编译 → 部署 → 核对；默认处理日文和中文，使用上一次游戏目录。

```powershell
.\check.ps1
```

等价于：

```powershell
python src\tools\check.py
```

Rust 构建与测试：

```powershell
cargo build --release --locked --target i686-pc-windows-msvc --manifest-path src\injector-rs\Cargo.toml
cargo test --locked --target i686-pc-windows-msvc --manifest-path src\injector-rs\Cargo.toml
```

Python 快速回归：

```powershell
python -m unittest tests.test_quick -v
```

提交前至少执行：

```powershell
git diff --check
```

涉及构建产物或部署时，再执行 release 构建、`check.py` 和 GUI 实机核对。

## 改动流程

1. **先确认状态**：`git status --short`、当前提交、工作树是否已有未提交改动。
2. **先读契约**：改 GUI/构建/语言包前读 `docs/架构与重构.md`；改译文前读
   `docs/译文与语言包.md`；改 API 前读 `docs/agent-api.md` 和 `src/editor/api/`。
3. **做最小改动**：不要顺手重写无关模块；不要把历史重构细节重新塞回当前架构文档。
4. **同步文档**：接口、文件路径、构建命令、支持范围或已知问题变化时，更新中文文档及相关入口。
5. **验证**：按改动范围跑对应检查；不能只凭截图、像素或字体宽度判断排版。
6. **提交**：默认新建提交，不 amend、不 force push；用户要求提交时再 push。

## 文档维护规则

- 文档索引只有 `docs/README.md` 一个入口。根目录新增文档必须进入这个索引。
- 当前架构写“现在是什么、文件契约、边界、已知问题”；已完成的阶段重构、旧路由变化、
  旧 C++ 文件对照写入 [历史重构记录](docs/历史重构记录.md)。
- 文档只维护中文一套；唯一英文文件是根目录 `README.en.md`，只写项目入口和支持语言，
  不复制完整文档。
- 文档和脚本里不写本机绝对路径：游戏目录写 `<游戏目录>`，用户目录用环境变量。
- 相对链接必须可解析；参考 `docs/agent-api.md` 当前 41 条路由的口径，路由变化时同时改
  中文文档和测试。
- 不要在文档里把“未验证”写成“已修复”，也不要把单次正常现象当成根因结论。

## 已知问题与验收口径

### 退出黑屏/白屏

- 现象：完成第一个教程战役后点「退出游戏」，`PR2.exe` 可能不退出，窗口黑屏或白屏残留；
  有时出现 MSVC Runtime Error，Program 指向 `PR2.exe`。
- 已复现：直接启动原版英文、用 `PR2LocalizationGUI` 启动原版、启动中文版都出现过。
  单次“原版正常”不能作为根因结论。
- 当前没有该路径的崩溃 dump，**根因未定位，状态是未修复**。
- GUI 的「结束游戏进程」只是兜底，仅结束 GUI 所在目录的 `PR2.exe`，不是修复。
  不要把它写成“已解决退出问题”。

### 排版与 DPI

- GUI 基准窗口为 `560x400`（96 DPI），当前系统 DPI 下实测过；更高 DPI 缩放未系统验证。
- 控件宽度是否足够，必须以实机控件矩形或真实运行结果为准；**不得用像素/字体宽度当
  排版判据**。
- 中文长句可能因引擎按空格切词而整条丢弃；这是已知引擎限制，不能只靠编辑器预览判断。

## 安全与仓库卫生

- 不删除用户的译文、字体、存档或游戏目录文件；`build/` 可重建，但删除前仍要确认。
- 不提交 `build/`、`target/`、`.venv/`、临时截图、临时测试目录和本机字体；
  先看 `.gitignore`，不要把生成物混进提交。
- 字体分发遵守 [字体与分发](docs/字体与分发.md)：发行包用完整 Noto；缝合字体只允许
  本机自用，不要上传、打包或提交。
- 未经明确要求不要部署到真实游戏目录；部署属于会改变外部状态的操作，先确认目标目录。
- 发现文档与代码不一致时，以代码和可复现实验为准，修文档或修代码，不要把错误口径
  继续复制到其他文档。
