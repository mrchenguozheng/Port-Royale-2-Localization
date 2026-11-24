# 参与开发

这份说明面向要提 issue、改译文或提交 PR 的人。玩家安装与卸载看 [README](README.md) 和[玩家指南](docs/玩家指南.md)；运行时原理、语言包格式和发行细节看[文档索引](docs/README.md)。

## 改动边界

- **原版文件只读。** 不修改 `src/orig/`、`assets/fonts/original/`，也不把游戏本体或原版 DLL 提交进仓库。
- **译文只改手写层。** 正文在 `src/translations/<语言>.toml`；包级元数据、`tags`、`review_status` 在 `src/packs/<语言>.toml`。不要直接改 `build/`、`dist/` 或安装目录里的产物。
- **生成物不手改。** `docs/语言矩阵.md`、`docs/实机截图.md`、`docs/screenshots.html`、缩略图等都是生成物；改源数据或模板后重新生成。`precommit.py` 会检查它们是否与生成器一致。
- **语言集已冻结。** 当前发行语言是 `zh`、`zh-TW`、`zh-HK`、`ja`、`ko`、`ru`、`de`、`es`、`fr`、`it`、`pl`、`pt-BR`；新增语言要先改发行规范与语言矩阵，不要只在 PR 里塞一份 TOML。

## 开发环境

- Windows 10 / 11
- Rust（rustup）与 `i686-pc-windows-msvc` target
- Python 3.11 以上（当前使用 3.15）
- MSVC 链接器（32 位 Rust target 需要；仓库不含 C++ 源码）

构建脚本全部是 Python，不需要 PowerShell。原版拉丁字体不入库，字体度量相关工作先从自己的游戏目录导出到 `assets/fonts/original/`。

## 改译文

1. 编辑 `src/translations/<语言>.toml`，键保持条目 id，值写译文。
2. 跑一遍完整链路：

```powershell
python apply_patch.py
```

它会依次做归一化 → 校验 → 编译 → 部署 → 核对。部署默认增量，只覆盖 `--lang` / `--langs` 指定的语言；要清理未列出的包才加 `--prune`。

3. 只看单门语言时可以收窄：

```powershell
python apply_patch.py --lang zh
```

4. 条目没写全不会报错，运行时回退英文；但发行语言要求待译 0，交付前用状态命令核对：

```powershell
python src\tools\translate.py status --lang zh
```

## 提交前检查

轻量闸门：

```powershell
python precommit.py
git config core.hooksPath .githooks   # 可选，让 git commit 自动跑
```

完整检查（含测试分片）：

```powershell
python check.py --skip-rust --jobs 4 --no-pause
```

涉及 Rust 改动时不要加 `--skip-rust`。涉及页面、截图或文档生成器时，至少确认：

```powershell
python src\tools\docs\build_screenshots.py --check
```

## 构建与发版

构建入口：

```powershell
python build.py                            # 注入器 + 全部语言包
python build.py --target packs --lang zh   # 只编中文语言包
python build.py --target injector          # 只编 Rust 注入器
```

发版入口：

```powershell
python release.py --version v1.0.0                  # 每个分组一个 zip，GOG / Steam 通用
python release.py --version v1.0.0 --bundle zh      # 只出中文分组
python release.py --version v1.0.0 --bundle latin   # 只出拉丁分组（de+es+fr+it+pt-BR）
python release.py --version v1.0.0 --allow-dirty    # 工作树脏时仍出包，版本头记 dirty
python release.py --version v1.0.0 --tag            # 创建本地 tag（要求干净树）
python release.py --version v1.0.0 --tag --push     # 再推送 tag
```

发版默认拒绝脏工作树，`--tag` 时无条件拒绝；`--tag` 只允许在当前分支 `main` 或 `release/*`。版本 tag 用普通 `vMAJOR.MINOR.PATCH`，已有 tag 不覆盖。

CI 对版本 tag 自动构建，但只生成 **draft GitHub Release**，正式发布由维护者决定。`dist/` 除分组 zip 与 `SHA256SUMS.txt` 外还会写 `release.json`（版本、提交、是否 dirty、分组与逐包 SHA-256），下游校验以它为准。

低层脚本在 `src/build_injector.py`、`src/build_translation.py`，日常不需要直接调用。每个 zip 根目录带 `manifest.json`，记录两个目标 exe、参考原文、翻译来源与 AI 标记、逐文件 SHA-256；出包前自校验，失败不出包。

## 仓库结构

```text
pr2-localization/
├─ build.py                   构建入口：注入器 + 语言包
├─ release.py                 发布入口：构建运行时 + 打 zip + 可选 tag
├─ apply_patch.py             归一化 → 校验 → 编译 → 部署
├─ shared/                   工具共用的存储/校验核心
├─ src/
│  ├─ translations/          译文唯一手改层（直接编辑 TOML）
│  ├─ packs/                 包级元数据、tags、review_status
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
├─ build/                    本地产物（gitignore）
├─ docs/                     说明文档
├─ glossary/                 术语对照表
└─ tests/                    规则与 API 单测
```

| 文件 | 角色 |
|---|---|
| `PR2Localization.exe` | 启动器。先校验/挂载宿主代理，GOG 版直启 `PR2.exe`，Steam 版交给客户端（构建产物） |
| `PR2LocalizationCore.dll` | 主逻辑。hook 引擎取字的三条路径，把译文替换进去（构建产物） |
| `PR2Localization\packs\` | 语言包目录。`<语言>.txt` + `locale.default.ini`；用户 `locale.ini` 优先；`overrides\` 是玩家补丁位 |
| `PR2Localization\fonts\` | 本地化字体；缺字会显示空白 |

## 加一种语言

不用碰注入器源码：

1. 用 `python src\tools\pack\new_lang.py --lang <代码> --template en` 生成 `src/translations/<代码>.toml`；
2. 编辑这个 TOML，逐条翻译；
3. 在 `src/tools/font/make_noto_fonts.py` 加该语言的 Noto 字重，并在 `src/font-map.ini` 加 `[<代码>]` 四条映射；
4. 构建字体、语言包并部署。

完整步骤（含每步验收点）见[新语言](docs/新语言.md)。

## Issue 与 PR

提 bug 时至少给：

- 游戏版本：GOG 英文 `1.1.2.3`、Steam 英文 `1.1.2.3` 或 GOG 法语 `1.1.2.42`
- `PR2Localization\logs\runtime.log`
- 挂载失败时再加 `PR2Localization\logs\host.log` / `proxy.log`
- 界面问题附截图，并写清当前文案与建议改法

提 PR 时：

- 一个 PR 只做一类改动，避免把译文、构建脚本和生成物混在一起
- 先跑 `precommit.py`，涉及行为改动再跑完整 `check.py`
- 不提交 `build/`、`dist/` 或本机绝对路径
- 不修改 `README.txt`、`manifest.json` 等包内产物；改源头后重新生成
- 不在 PR 里自行发布 Release；tag 触发的只是 draft

## 路径约定

仓库里的文档与脚本**不写本机绝对路径**：游戏目录一律写作 `<游戏目录>`，用户目录用 `%USERPROFILE%` 之类的环境变量表示。

`extract_fonts.py` 需要的原版字体默认读仓库内 `assets/fonts/original/`（已在 `.gitignore` 中忽略），不再指向某台机器的安装位置；它只用于测量原版字体度量。

## 相关文档

- [文档索引](docs/README.md)
- [构建与安装](docs/构建与安装.md)
- [译文与语言包](docs/译文与语言包.md)
- [新语言](docs/新语言.md)
- [发行规范](docs/发行规范.md)
- [注入组件](docs/注入组件.md)
- [运行契约](docs/运行契约.md)
