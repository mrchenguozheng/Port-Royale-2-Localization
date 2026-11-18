# Port Royale 2 本地化

《Port Royale 2》的本地化项目：**用外挂语言包替换界面文本，原版 `PR2.exe` 全程不改。**

[English](README.en.md) · [中文文档索引](docs/README.md)

**Supported languages:** Simplified Chinese (`zh`), Japanese (`ja`); English (`en`) is the original game language and fallback. See [README.en.md](README.en.md#supported-languages).

---

## 快速开始（玩家）

不需要安装器、不需要 Python、不需要编译。

1. 确认是 **GOG 英文版 `1.1.2.3`**，或 Steam 英文版 `1.1.2.3`（宿主 DLL 入口）；
2. 从 Release 下载对应语言和入口的 zip：GOG 版是 `PR2-zh-gog-v1.0.0.zip`，
   Steam 版是 `PR2-zh-steam-v1.0.0.zip`；
3. **全部解压到 `PR2.exe` 所在的游戏根目录**；
4. GOG 双击 `PR2LocalizationGUI.exe`，选语言后点「以所选语言启动」；
   Steam 先在游戏根目录运行 `PR2HostMount.ps1 -Action Mount`，再从 Steam 启动游戏；
5. 进游戏后看 `PR2Localization\logs\runtime.log`，第一行应有 `pack 'zh' ... overrides`。

GOG 包刻意不含 `VERSION.dll`。Steam 包不带 `VERSION.dll`，而是带
`Ascaron.Logging-2.6.dll` 宿主代理和 `PR2HostMount.ps1`：挂载脚本先校验原版
`Ascaron.Logging-2.6.dll` 的 `11,776 B` / SHA-256，通过后备份成
`Ascaron.Logging-2.6.orig.dll` 和 `PR2Localization\host-backup\`，再换代理；
原版大小或哈希不对时脚本停止，不强行覆盖。GOG 从旧包升级时，根目录残留的
`VERSION.dll` 可以删除，GOG 不加载它。
GOG 不要直接双击 `PR2.exe`：GOG 的加载器会把 `VERSION.dll` 解析到
`C:\Windows\SysWOW64\VERSION.dll`，同目录代理不会进入游戏进程，结果是原版英文。
`PR2Localization.exe` / `PR2LocalizationGUI.exe` 是 GOG 的正式入口，负责注入
`PR2LocalizationCore.dll`；原版 `PR2.exe` 本身不改。

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

**本项目用于给英文版套其他语言包；原版 `PR2.exe` 不改。**

| 游戏版本 | 状态 |
|---|---|
| **GOG 英文 `1.1.2.3`** | ✅ 已实测（`PR2LocalizationGUI` 入口） |
| **Steam 英文 `1.1.2.3`** | ✅ 已实测（宿主 `Ascaron.Logging-2.6.dll` 代理，中文界面） |
| GOG 法语 `1.1.2.42` | ❌ 不支持（只用作翻译参照） |
| 其他版本 | ❌ 不支持 |

Steam 版不再尝试 `VERSION.dll` 自然加载：`PR2.exe` 静态导入
`Ascaron.Logging-2.6.dll`，本项目的代理接管这个导出，并在工作线程里加载同目录
`PR2LocalizationCore.dll`；后者等待 `A2dLib-2.20A.dll` 后再装 hook。
挂载和还原都经过 `Ascaron.Logging-2.6.dll` 的大小/SHA-256 校验，未知文件不覆盖。
未验证的版本不要反馈“汉化已支持”，先附 `PR2Localization\logs\runtime.log` 和
`PR2Localization\logs\proxy.log`。

---

## 开发者：构建与翻译

需要 Rust（rustup + `i686-pc-windows-msvc` target）+ Python 3.11 以上（当前用 3.15）+ PowerShell 7（`pwsh`）+ MSVC 链接器（Rust 32 位 target 需要；项目不含 C++ 源码）。

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
- **语言**：「设为游戏语言」写 `PR2Localization/packs/locale.ini`；发行包只带 `locale.default.ini`，已有活动文件不覆盖；
- **译文编辑**：和安装页同一个工作台，顶部页签切换。

开发时改完译文，也可以直接在 PowerShell 7 运行 `pwsh -NoProfile -ExecutionPolicy Bypass -File .\apply_patch.ps1`：归一化 → 校验 → 编译 → 部署 → 核对一次跑完。

构建入口收成根目录两个脚本：

```powershell
.\build.ps1                         # 注入器 + 全部语言包（zh、ja）
.\build.ps1 -Target Packs -Lang zh  # 只编中文语言包
.\build.ps1 -Target Injector        # 只编 Rust 注入器

.\release.ps1 -Version v1.0.0       # 同时生成 gog 和 steam 两套 zip
.\release.ps1 -Version v1.0.0 -Edition gog    # 只出 GOG 包
.\release.ps1 -Version v1.0.0 -Edition steam  # 只出 Steam 包
.\release.ps1 -Version v1.0.0 -Tag  # 额外创建 release-v1.0.0 本地 tag
.\release.ps1 -Version v1.0.0 -Tag -Push  # 再推送 tag
```

低层脚本仍在 `src\build_injector.ps1`、`src\build_translation.ps1`；日常不需要直接调用。
每个 zip 根目录带 `manifest.json`，记录目标 exe、参考原文、翻译来源/AI 标记和逐文件
SHA-256；出包前自校验，失败不出包。
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
│     ├─ font/               字体生成、调整与导出
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
| `PR2Localization.exe` | 启动器。挂起方式启动 `PR2.exe`，注入 DLL 后恢复执行（构建产物） |
| `PR2LocalizationCore.dll` | 主逻辑。hook 引擎取字的三条路径，把译文替换进去（构建产物） |
| `PR2Localization\packs\` | 语言包目录。`<语言>.txt` + `locale.default.ini`（发行默认）；用户 `locale.ini` 优先 |
| `PR2Localization\fonts\` | 本地化字体；缺字会显示空白 |

## 加一种语言

不用碰注入器源码，流程是：

1. 在 PowerShell 7 运行 `pwsh -NoProfile -ExecutionPolicy Bypass -File .\start.ps1`，在「译文编辑」页点语言下拉旁的「＋」，用现成语言当模板；
2. 逐条翻译并保存（写进 `src/translations/<代码>.toml`）；
3. 在 `src/tools/font/make_noto_fonts.py` 加该语言的 Noto 字重，并在 `src/font-map.ini` 加 `[<代码>]` 四条映射；
4. 构建字体、语言包并部署。

完整步骤（含每步验收点）见[新语言](docs/新语言.md)。

条目不必写全 —— 没写的自动显示英文。

---

## 文档

| 文档 | 内容 |
|---|---|
| [文档索引](docs/README.md) | 按“玩家/构建/开发/数据”分类，先查这里 |
| [玩家指南](docs/玩家指南.md) | 下载 zip、解压、启动、卸载、常见问题 |
| [构建与安装](docs/构建与安装.md) | 安装页、构建/部署/启动、脚本一览 |
| [新语言](docs/新语言.md) | 从字体准备到翻译、部署、验收、出包 |
| [发行版](docs/发行版.md) | 按语言出 zip、Noto 字体、GitHub Actions |
| [字体与分发](docs/字体与分发.md) | 字体映射、Noto 许可、禁止分发 |
| [注入组件](docs/注入组件.md) | 运行时原理、hook 三条路径、源码职责、编译 |
| [架构与重构](docs/架构与重构.md) | 分层、文件契约、重构记录、已知边界 |
| [译文与语言包](docs/译文与语言包.md) | toml 格式、校验规则、加一种语言 |
| [术语对照](glossary/README.md) | 货物/船只/军衔/城镇等专名的英中对照，可扩展到别的语言 |
| [待定事项](docs/待定.md) | 尚未完成或未验证的方向 |
| [说话人分级](docs/说话人分级.md) | 哪些台词能确定说话人、哪些只能猜（附逐条 CSV） |
| [翻译局限](docs/翻译局限.md) | 哪些问题无法根除、实际验证到几成、要不要 hook |
| [语体拟改清单](docs/语体拟改清单.md) | 能确定说话人的 41 条 + 待人工的 668 条 |

---

## 已知限制

- **hook 目标与游戏版本绑定。** 代码按固定偏移取 `A2dLib-2.20A.dll` 的函数，
  换游戏版本（包括 GOG 的法语版 `1.1.2.42`）很可能需要改偏移，否则整体不生效。
- **中文条目整条不显示是分词问题，不是标签问题。** 引擎按空格切词，
  整串汉字超宽会被整条丢弃，只能逐条在游戏里实测。
- **字体统一放在 `PR2Localization\fonts\`。** 实际字体文件（默认保留 Noto 原始文件名）平铺，
  不按语言子目录；同一次安装只放一个语言。四个游戏逻辑名由 `font-map.ini` 映射到这些文件，
  发行包只带 `font-map.default.ini`；用户自定义的 `font-map.ini` 按项覆盖，解压升级不覆盖它。
  映射只接受 fonts 内的文件。字体只做映射：直接用完整 Noto（俄语用四个自建文件），
  部署时复制到游戏 `PR2Localization\fonts\`，不覆盖根目录原版；没有缝合步骤，
  译文新增生僻字由完整字重本身覆盖。

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
`extract_fonts.py` 需要的原版字体默认读仓库内 `assets/fonts/original/`（已在 `.gitignore` 中忽略），
不再指向某台机器的安装位置；它只用于测量原版字体度量。
