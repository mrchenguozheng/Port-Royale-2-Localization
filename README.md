# Port Royale 2 本地化

《Port Royale 2》的本地化项目：**用外挂语言包替换界面文本，原版 `PR2.exe` 全程不改。**

[English](README.en.md) · [中文文档索引](docs/README.md)

**Supported languages:** Simplified Chinese (`zh`), Japanese (`ja`), Korean (`ko`), Russian (`ru`), German (`de`), Spanish (`es`), French (`fr`), Italian (`it`), Polish (`pl`); English (`en`) is the original game language and fallback. See [README.en.md](README.en.md#supported-languages).

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

1. 确认系统是 **Windows 10 / Windows 11**（不支持 Windows 7）；
2. 确认是 **GOG 英文版 `1.1.2.3`**、Steam 英文版 `1.1.2.3`，或 GOG 法语版 `1.1.2.42`（三者都走宿主 DLL 入口）；
3. 从 Release 下载对应语言的 zip，例如中文是 `PR2-zh-v1.0.0.zip`——**一个包两种版本都能用**；
4. **全部解压到 `PR2.exe` 所在的游戏根目录**；
5. **双击 `PR2LocalizationGUI.exe`**，选语言后点「以所选语言启动」：
   GOG 版由启动器挂载宿主 DLL 后直启游戏；Steam 版挂载后交给 Steam 客户端
   （`steam://rungameid/12470`）拉起，不用你回库里再点一次；
6. 进游戏后看 `PR2Localization\logs\runtime.log`，第一行应有 `pack 'zh' ... N entries, M overrides`。
7. 想确认装的是哪一版：GUI 副标题与语言列表都带版本（`简体中文 · v1.0.0`），
   命令行 `PR2Localization.exe --version` 打印同一串；语言包改了什么看状态框第二行
   （`3590 条 · 未译 0 · 摘要 9cfa2931c1c2`）与包根 `README.txt` 的「语言包变化」段。
8. 想回原版：点 GUI 上的「还原原版」，或 `PR2Localization.exe --restore`。

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

两版都不尝试 `VERSION.dll` 自然加载：`PR2.exe` 静态导入
`Ascaron.Logging-2.6.dll`，本项目的代理接管这个导出，并在工作线程里加载同目录
`PR2LocalizationCore.dll`；后者等待 `A2dLib-2.20A.dll` 后再装 hook。
`VERSION.dll` 属于 Windows 的 KnownDLLs，同目录代理永远进不去，那条路线已废弃。
挂载和还原都经过 `Ascaron.Logging-2.6.dll` 的大小/SHA-256 校验，未知文件不覆盖。
未验证的版本不要反馈“汉化已支持”，先附 `PR2Localization\logs\runtime.log` 和
`PR2Localization\logs\proxy.log`。

---

## 开发者：构建与翻译

需要 Rust（rustup + `i686-pc-windows-msvc` target）+ Python 3.11 以上（当前用 3.15）+ MSVC 链接器（Rust 32 位 target 需要；项目不含 C++ 源码）。构建脚本全是 Python，不需要 PowerShell。

开发时改译文直接编辑 `src\translations\<语言>.toml`，然后：

```powershell
python apply_patch.py
```

它一次跑完归一化 → 校验 → 编译 → 部署 → 核对。部署默认增量：只覆盖
`--lang`/`--langs` 列出的语言，未列出的包保留；要清理才加 `--prune`。

提交前可跑轻量闸门：

```powershell
python precommit.py
git config core.hooksPath .githooks   # 可选：git commit 自动跑
```

构建入口：

```powershell
python build.py                         # 注入器 + 全部语言包
python build.py --target packs --lang zh  # 只编中文语言包
python build.py --target injector        # 只编 Rust 注入器

python release.py --version v1.0.0       # 每个分组一个 zip（GOG / Steam 通用）
python release.py --version v1.0.0 --bundle zh     # 只出中文分组
python release.py --version v1.0.0 --bundle latin  # 只出拉丁分组（de+es+fr+it）
python release.py --version v1.0.0 --allow-dirty   # 工作树脏时仍出包；版本头记 dirty
python release.py --version v1.0.0 --tag           # 创建 v1.0.0 本地 tag（要求干净树）
python release.py --version v1.0.0 --tag --push    # 再推送 tag
```

发版默认拒绝脏工作树，`--tag` 时无条件拒绝；`--tag` 只允许在当前分支 `main` 或 `release/*`。
版本 tag 用普通 `vMAJOR.MINOR.PATCH`，已有 tag 不覆盖。CI 对每个版本 tag 自动构建，
但只生成 **draft GitHub Release**；由维护者自己挑一个正式发布。
`dist\` 除七个 zip 与 `SHA256SUMS.txt` 外，还会写 `release.json`（版本、提交、是否 dirty、
分组与逐包 SHA-256），CI 与下游校验以它为准。

低层脚本在 `src\build_injector.py`、`src\build_translation.py`；日常不需要直接调用。
每个 zip 根目录带 `manifest.json`，记录两个目标 exe（GOG 与 Steam）、参考原文、
翻译来源/AI 标记和逐文件
SHA-256；出包前自校验，失败不出包。
脚本位置和参数见[构建与安装](docs/构建与安装.md#脚本位置)。
每个 zip 根目录带 `manifest.json`，记录两个目标 exe（GOG 与 Steam）、参考原文、
翻译来源/AI 标记和逐文件
SHA-256；出包前自校验，失败不出包。
脚本位置和参数见[构建与安装](docs/构建与安装.md#脚本位置)。

### 仓库结构

```
pr2-localization/
├─ build.py                   构建入口：注入器 + 语言包
├─ release.py                 发布入口：构建运行时 + 打 zip + 可选 tag
├─ apply_patch.py             归一化 → 校验 → 编译 → 部署
├─ shared/                   工具共用的存储/校验核心
├─ src/
│  ├─ translations/          译文唯一手改层（直接编辑 TOML）
│  ├─ data/                  人工维护的数据（占位符语义、原样保留清单）
│  ├─ orig/                  原版英文/法文（只读参照）
│  ├─ injector-rs/           注入组件源码（Rust workspace，含 ui/）
│  └─ tools/
│     ├─ pack/               编译、部署、新建语言
│     ├─ text/               归一化、中文/日文规则、分词
│     ├─ font/               字体生成、调整与导出
│     ├─ analysis/           说话人、语气等分析
│     ├─ install/            pr2ctl 构建/部署/启动实现
│     └─ data/               人名、地名、分词词典
├─ assets/fonts/original/    游戏原版拉丁字体（gitignore，需自己导出）
├─ build/                    本地产物（gitignore）：runtime/（部署根）、variants/（逐版包）、
│                            qa/（报告与一次性脚本）、cache/（字体缓存）、
│                            notes/（提交草稿、批次映射、改前快照、试验数据）、tools/（清理脚本）
├─ docs/                     说明文档
├─ glossary/                 术语对照表
└─ tests/                    规则与 API 单测
```

| 文件 | 角色 |
|---|---|
| `PR2Localization.exe` | 启动器。先校验/挂载宿主代理，GOG 版直启 `PR2.exe`，Steam 版交给客户端（构建产物） |
| `PR2LocalizationCore.dll` | 主逻辑。hook 引擎取字的三条路径，把译文替换进去（构建产物） |
| `PR2Localization\packs\` | 语言包目录。`<语言>.txt` + `locale.default.ini`（发行默认）；用户 `locale.ini` 优先；`overrides\` 是空的覆盖位，玩家自己往里放补丁 |
| `PR2Localization\fonts\` | 本地化字体；缺字会显示空白 |

## 加一种语言

不用碰注入器源码，流程是：

1. 用 `python src\tools\pack\new_lang.py --lang <代码> --template en` 生成 `src/translations/<代码>.toml`；
2. 直接编辑这个 TOML，逐条翻译；
3. 在 `src/tools/font/make_noto_fonts.py` 加该语言的 Noto 字重，并在 `src/font-map.ini` 加 `[<代码>]` 四条映射；
4. 构建字体、语言包并部署。

完整步骤（含每步验收点）见[新语言](docs/新语言.md)。

条目不必写全 —— 没写的自动显示英文。

---

## 文档

完整分类见[文档索引](docs/README.md)，这里只列最常用的几篇：

| 文档 | 内容 |
|---|---|
| [运行契约](docs/运行契约.md) | 支持环境、包内布局、界面语言、宿主挂载的唯一口径 |
| [玩家指南](docs/玩家指南.md) | 下载 zip、解压、启动、卸载、常见问题 |
| [构建与安装](docs/构建与安装.md) | 构建/部署/启动、脚本一览 |
| [译文与语言包](docs/译文与语言包.md) | TOML 格式、校验规则、两版键集与出包取值 |
| [注入组件](docs/注入组件.md) | 运行时原理、hook 三条路径、源码职责 |
| [发行规范](docs/发行规范.md) | 版本号、发行语言集、产物与校验和、tag |
| [待定事项](docs/待定.md) | 尚未完成或未验证的方向 |
| [术语对照](glossary/README.md) | 货物/船只/军衔/城镇等专名的英中对照 |

---

## 已知限制

- **hook 目标与游戏版本绑定。** 代码按固定偏移取 `A2dLib-2.20A.dll` 的函数。
  已知的三个版本（GOG 英文 `1.1.2.3`、Steam 英文 `1.1.2.3`、GOG 法语 `1.1.2.42`）
  都用同一组偏移并已实测；换其他版本（零售版、补丁版）很可能需要改偏移，否则整体不生效。
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

十二门发行语言共用一套 3548 条基准（`en.gog_1.1.2.3`），"有意不译"指按键名、职员表、游戏
标题、场景文件名模板、纯符号与空占位、以及**原文就是本语言写法**的专名（城镇名、
海盗与姓氏池）这类按规则保留原文的条目（登记在 `src/data/keep_as_is/`），不计入待译。
所以「可译 = 3548 − 有意不译」，百分比按 **已译 / 可译** 算。数字会变，取实时值时跑
`python src\tools\translate.py status --lang <代码>`；清单本身对不对账，
`python src\tools\analysis\keep_audit.py` 会逐语言点名。

| 语言 | 已译 / 可译 | 待译 | 有意不译 |
|---|---|---|---|
| 中文 `zh` | 3428 / 3428（100%） | 0 | 120 |
| 日语 `ja` | 3451 / 3451（100%） | 0 | 97 |
| 韩语 `ko` | 3454 / 3454（100%） | 0 | 94 |
| 俄语 `ru` | 3439 / 3439（100%） | 0 | 109 |
| 德语 `de` | 3015 / 3015（100%） | 0 | 533 |
| 西班牙语 `es` | 3099 / 3099（100%） | 0 | 449 |
| 法语 `fr` | 2988 / 2988（100%） | 0 | 560 |
| 波兰语 `pl` | 2904 / 2904（100%） | 0 | 644 |
| 意大利语 `it` | 3007 / 3007（100%） | 0 | 541 |
| 葡萄牙语（巴西） `pt-BR` | 3005 / 3481（86.3%） | 476 | 67 |
| 英文 / 法文原文 | 参照（`src/orig/`） | 不出包 |

「有意不译」多出来的那部分正是各语言自己登记的本语言按键名/表头。日语里的「原样
保留」指本来就不该翻译、与英文原文相同的条目：纯符号/数字、引擎编号
（`IDM_CONTEST_…`）、按键名（`ESC`/`CTRL`/`F10`）、版权声明与制作方名称。
编译时强制写回英文原文的只有 `compile_pack.py` 的 `KEEP_ORIGINAL` 表（目前一条）。

## 路径约定

仓库里的文档与脚本**不写本机绝对路径**：游戏目录一律写作 `<游戏目录>`，
用户目录用 `%USERPROFILE%` 之类的环境变量表示。
`extract_fonts.py` 需要的原版字体默认读仓库内 `assets/fonts/original/`（已在 `.gitignore` 中忽略），
不再指向某台机器的安装位置；它只用于测量原版字体度量。
