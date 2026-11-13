# Port Royale 2 本地化

《Port Royale 2》的本地化项目：**用外挂语言包替换界面文本，原版 `PR2.exe` 全程不改。**

[English](README.en.md) · [中文文档索引](docs/README.md)

**Supported languages:** Simplified Chinese (`zh`), Japanese (`ja`); English (`en`) is the original game language and fallback. See [README.en.md](README.en.md#supported-languages).

---

## 快速开始（玩家）

不需要安装器、不需要 Python、不需要编译。

1. 确认是 **GOG 英文版 `1.1.2.3`**，或 Steam 英文版（实验性）；
2. 从 Release 下载对应语言的 zip，例如 `PR2-zh-v1.0.0.zip`；
3. **全部解压到 `PR2.exe` 所在的游戏根目录**；
4. GOG 双击 `PR2.exe`；Steam 直接从 Steam 启动游戏；
5. 进游戏后看 `PR2TextSource.log`，第一行应有 `pack 'zh' ... overrides`。

`VERSION.dll` 是代理宿主，游戏会自然加载同目录的 `PR2TextSource.dll`；
不需要启动器，也不需要远程注入。仍然可以双击 `PR2LauncherGUI.exe`，
选语言后点「以所选语言启动」，作为代理冲突时的备用入口。

注意：

- 目录里已有别的 mod 占用 `VERSION.dll` 时，先移除本包的 `VERSION.dll`，
  改用 `PR2LauncherGUI.exe`；
- 不要删除 `fonts\` 根目录的四份原版字体；
- 缺字体时 GUI 会提示，把 zip 里的 `fonts\<语言>\` 重新解压完整即可。

完整步骤、卸载和常见问题见[玩家指南](docs/玩家指南.md)。

---

## 支持范围

**本项目用于给英文版套其他语言包；原版 `PR2.exe` 不改。**

| 游戏版本 | 状态 |
|---|---|
| **GOG 英文 `1.1.2.3`** | ✅ 已实测 |
| **Steam 英文（当前测试目录）** | 🟡 实验性：`VERSION.dll` 代理加载链已构建，待进游戏验证 |
| GOG 法语 `1.1.2.42` | ❌ 不支持（只用作翻译参照） |
| 其他版本 | ❌ 不支持 |

Steam 版不再依赖启动器远程注入：`PR2.exe` 导入 `VERSION.dll`，本项目的
`VERSION.dll` 转发系统 version API，并在工作线程里加载同目录
`PR2TextSource.dll`；后者等待 `A2dLib-2.20A.dll` 后再装 hook。
未验证的版本不要反馈“汉化已支持”，先附 `PR2TextSource.log` 和
`PR2Proxy.log`。

---

## 开发者：构建与翻译

需要 Rust（rustup + `i686-pc-windows-msvc` target）+ Python 3.11 以上（当前用 3.15）+ PowerShell 7（`pwsh`）。

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

它启动本地工作台服务，打开浏览器到「安装与启动」页，**不自动编译**。

页面顶部是五步安装向导：

1. 准备游戏目录；
2. 准备字体；
3. 翻译内容；
4. 生成语言包 + 字体；
5. 安装并启动。

也可以直接点下面的卡片：

- **构建与部署**：编译注入器、编译语言包、部署到游戏目录；
- **启动**：「设为游戏语言」写 `locale.ini`，「启动游戏（已注入）」按当前下拉语言启动；
- **译文编辑**：和安装页同一个工作台，顶部页签切换。

开发时改完译文，也可以直接在 PowerShell 7 运行 `pwsh -NoProfile -ExecutionPolicy Bypass -File .\apply_patch.ps1`：归一化 → 校验 → 编译 → 部署 → 核对一次跑完。

构建入口收成根目录两个脚本：

```powershell
.\build.ps1                         # 注入器 + 全部语言包（zh、ja）
.\build.ps1 -Target Packs -Lang zh  # 只编中文语言包
.\build.ps1 -Target Injector        # 只编 Rust 注入器

.\release.ps1 -Version v1.0.0       # 构建运行时 + 生成 dist\PR2-<语言>-<版本>.zip
.\release.ps1 -Version v1.0.0 -Tag  # 额外创建 release-v1.0.0 本地 tag
.\release.ps1 -Version v1.0.0 -Tag -Push  # 再推送 tag
```

低层脚本仍在 `src\build_injector.ps1`、`src\build_translation.ps1`；日常不需要直接调用。
脚本位置和参数见[构建与安装](docs/构建与安装.md#脚本位置)。

按钮细节见[构建与安装](docs/构建与安装.md)。

### 仓库结构

```
pr2-localization/
├─ start.ps1                  开发入口：启动工作台
├─ build.ps1                  构建入口：注入器 + 语言包
├─ release.ps1                发布入口：构建运行时 + 打 zip + 可选 tag
├─ apply_patch.ps1            归一化 → 校验 → 编译 → 部署
├─ shared/                   编辑器与工具共用的存储/校验核心
├─ src/
│  ├─ translations/          译文唯一手改层（编辑器保存到这里）
│  ├─ data/                  人工维护的数据（占位符语义、原样保留清单）
│  ├─ orig/                  原版英文/法文（只读参照）
│  ├─ editor/                译文编辑器（Astro 前端 + server.py，api/ 按域分模块）
│  ├─ injector-rs/           注入组件源码（Rust workspace，含 ui/）
│  └─ tools/
│     ├─ pack/               编译、部署、新建语言
│     ├─ text/               归一化、中文/日文规则、分词
│     ├─ font/               字体缝合与导出（含 fontstitch/）
│     ├─ analysis/           说话人、语气等分析
│     ├─ install/            pr2ctl 构建/部署/启动实现
│     └─ data/               人名、地名、分词词典
├─ assets/fonts/original/    游戏原版拉丁字体（gitignore，需自己导出）
├─ build/                    产物：runtime/（部署根）、preview/（查看）、cache/（缓存）
├─ docs/                     说明文档
├─ glossary/                 术语对照表
└─ tests/                    规则与 API 单测
```

| 文件 | 角色 |
|---|---|
| `PR2Launcher.exe` | 启动器。挂起方式启动 `PR2.exe`，注入 DLL 后恢复执行（构建产物） |
| `PR2TextSource.dll` | 主逻辑。hook 引擎取字的三条路径，把译文替换进去（构建产物） |
| `PR2Packs\` | 语言包目录。`<语言>.txt` + `locale.ini`，可直接改文本 |
| `fonts\` | 本地化字体；缺字会显示空白 |

## 加一种语言

不用碰注入器源码，流程是：

1. 在 PowerShell 7 运行 `pwsh -NoProfile -ExecutionPolicy Bypass -File .\start.ps1`，在「译文编辑」页点语言下拉旁的「＋」，用现成语言当模板；
2. 逐条翻译并保存（写进 `src/translations/<代码>.toml`）；
3. 创建语言时会自动生成 `presets/<代码>.toml`（donor 以模板语言的文件为模板），
   再按语种检查/替换 donor；
4. 构建字体、语言包并部署。

完整步骤（含每步验收点）见
[新语言完整流程](docs/新语言完整流程.md)；只需要准备哪些东西见
[新语言字体配置](docs/新语言字体配置.md)。

条目不必写全 —— 没写的自动显示英文。

---

## 文档

| 文档 | 内容 |
|---|---|
| [文档索引](docs/README.md) | 按“玩家/开发/翻译/待定”分类，先查这里 |
| [玩家指南](docs/玩家指南.md) | 下载 zip、解压、启动、卸载、常见问题 |
| [构建与安装](docs/构建与安装.md) | 安装页、构建/部署/启动、脚本一览 |
| [新语言完整流程](docs/新语言完整流程.md) | 从导出字体到进游戏，按步骤做 |
| [新语言协作流程](docs/新语言协作流程.md) | 译者能做什么、维护者能做什么 |
| [发行版](docs/发行版.md) | 按语言出 zip、Noto 字体、GitHub Actions |
| [新语言字体配置](docs/新语言字体配置.md) | 别人做新语言需要准备哪些字体和工具 |
| [字体与分发](docs/字体与分发.md) | 缝合原理、donor 许可、禁止分发 |
| [注入组件](docs/注入组件.md) | 运行时原理、hook 三条路径、源码职责、编译 |
| [架构与重构](docs/架构与重构.md) | 分层、文件契约、重构记录、已知边界 |
| [译文与语言包](docs/译文与语言包.md) | toml 格式、校验规则、加一种语言 |
| [术语对照](glossary/README.md) | 货物/船只/军衔/城镇等专名的英中对照，可扩展到别的语言 |
| [待定事项](docs/待定.md) | Steam 不生效、法文版未验证、hook 偏移等还没结论的问题 |
| [说话人分级](docs/说话人分级.md) | 哪些台词能确定说话人、哪些只能猜（附逐条 CSV） |
| [翻译局限](docs/翻译局限.md) | 哪些问题无法根除、实际验证到几成、要不要 hook |
| [语体拟改清单](docs/语体拟改清单.md) | 能确定说话人的 41 条 + 待人工的 668 条 |

---

## 已知限制

- **hook 目标与游戏版本绑定。** 代码按固定偏移取 `A2dLib-2.20A.dll` 的函数，
  换游戏版本（包括 GOG 的法语版 `1.1.2.42`）很可能需要改偏移，否则整体不生效。
- **中文条目整条不显示是分词问题，不是标签问题。** 引擎按空格切词，
  整串汉字超宽会被整条丢弃，只能逐条在游戏里实测。
- **字体按语言分开。** 开发用缝合版 `build\runtime\fonts\<语言>\`，发行用完整 Noto；
  部署时复制到游戏 `fonts\<语言>\`，不覆盖根目录原版。译文新增生僻字时，
  构建会自动重缝，缺字就会显示空白。

---

## 许可

见 [LICENSE](LICENSE).

## 语言完成度

| 语言 | 条目 | 状态 |
|---|---|---|
| 中文 `zh` | 3548 | ✅ 全部完成（含排版与占位符校验） |
| 日语 `ja` | 3548 | ✅ 全部完成（3370 条译文 + 178 条「原样保留」） |
| 英文/法文 | 3548 | 参照原文（`src/orig/`），不生成语言包 |

日语里的「原样保留」指本来就不该翻译、与英文原文相同的 178 条：纯符号/数字、
引擎编号（`IDM_CONTEST_…`）、按键名（`ESC`/`CTRL`/`F10`）、版权声明与制作方名称。
其中编译时强制写回英文原文的，只有 `compile_pack.py` 的 `KEEP_ORIGINAL` 表
（目前是版权声明一条）。

## 路径约定

仓库里的文档与脚本**不写本机绝对路径**：游戏目录一律写作 `<游戏目录>`，
用户目录用 `%USERPROFILE%` 之类的环境变量表示。
`subset_fonts.py` 需要的原版字体默认读仓库内 `assets/fonts/original/`（已在 `.gitignore` 中忽略），
不再指向某台机器的安装位置。
