# src/tools 脚本地图

脚本按用途分目录：

```
src/tools/
├─ pack/       编译、部署、新建语言
├─ text/       归一化、中文/日文规则、分词
├─ font/       字体缝合与导出
├─ analysis/   说话人、语气等分析
├─ install/    pr2ctl 构建/部署/启动
├─ data/       人名、地名、分词词典
├─ translate.py / glossary.py / terms_check.py / placeholder_roles.py   共享核心
├─ extract_strings.py                                                  从 PR2.exe 重提基准原文
├─ check.py / lint_imports.py                                          质量检查
└─ paths.py    公共路径
```

## 基准原文

| 脚本 | 作用 |
|---|---|
| `extract_strings.py` | 从 `PR2.exe` 的 PE 资源（`BINARY/167`）解出字符串表写成 toml；换游戏版本、或要对照别的语言版本时，用它重建 `src/orig/*.toml` |

## 常用入口

| 脚本 | 作用 |
|---|---|
| `pack/apply_patch.py` | 校验 → 编译 → 部署，一条命令跑完（`apply_patch.bat` 调它） |
| `check.py` | 跑全部静态检查与单测（`check.bat` 调它） |
| `pack/new_lang.py` | 命令行新建语言（编辑器里也能建） |
| `pack/compile_pack.py` | 把 `src/translations/*.toml` 排版后编译成 `build/PR2Packs/*.txt`，引擎文本落在 `build/engine_text/*.toml` |
| `pack/check_breaks.py` | 编译后校验换行/占位符 |

## 文本规则

| 脚本 | 作用 |
|---|---|
| `text/normalize_text.py` | 按语言规则归一化标点（只改标点，不补排版空格） |
| `text/engine_text.py` | 译文 → 引擎文本（**唯一构建入口**，只认 lang_rules 的 spec；`--check/--stats/--diff`） |
| `text/lang_rules/spec.py` | 三段式接口：`Punctuation` / `Segmenter` / `Spacing` + `LangSpec` + 执行器 |
| `text/apply_zh_rules.py` | 中文旧名的兼容门面（`fix_conj`、`space_tokens`、`generate_doc` 等），新代码用 `zh_pipeline` |
| `text/zh_pipeline.py` | 中文「分词前」：连词、人名、数字/破折号/`<n><n>` 空格 |
| `text/zh_space.py` | 中文分词与按字数成组补空格（spaCy → jieba → 机械兜底） |
| `text/toml_io.py` | 译文/产物共用的 TOML 读写（id 顺序、转义、header） |
| `text/segment_zh.py` | spaCy 分词子进程入口 |
| `data/zh_names.txt` / `data/zh_towns.txt` / `data/zh_userdict.txt` | 人名、地名、分词词典 |

## 翻译与术语

| 脚本 | 作用 |
|---|---|
| `translate.py` | 调模型批量翻译 |
| `glossary.py` | 术语表读取/应用 |
| `terms_check.py` | 术语一致性检查 |
| `placeholder_roles.py` | 占位符语义与角色 |
| `analysis/speaker_audit.py` / `analysis/tone_proposal.py` / `analysis/voice_match.py` | 说话人、语气、称谓分析 |

## 字体

| 路径 | 作用 |
|---|---|
| `font/subset_fonts.py` | 字体缝合入口（进阶/自用，每个语言 `presets/<语言>.toml`） |
| `font/make_noto_fonts.py` | 发行版 Noto 替换字体（完整字体，不裁剪） |
| `font/extract_fonts.py` | 从游戏 `pr2_loca.cpr` 导出原版拉丁字体 |
| `font/fontstitch/` | 缝合引擎、`presets/` 目录、校验工具 |
| `pack/make_release.py` | 按语言生成发行 zip（语言包 + 启动器 + Noto 字体） |

字体前置检查：

```bash
python src/tools/font/subset_fonts.py --check
```

## 构建、安装与诊断

| 路径 | 作用 |
|---|---|
| `install/pr2ctl/` | 构建/部署/启动的共享实现 |
| `install/server_status.py` | 探测本机编辑器实例 |
| `analysis/progress.py` | 进度显示 |
| `lint_imports.py` | 跨模块引用检查 |

## 数据文件

| 文件 | 内容 |
|---|---|
| `data/zh_names.txt` | 中文人名/地名匹配表 |
| `data/zh_towns.txt` | 城镇名 |
| `data/zh_userdict.txt` | 分词用户词典 |

## 约定

- 各组脚本把 `src/tools` 加进 `sys.path`，共享模块（`translate.py` 等）仍在根目录；
- 组内脚本运行时用 `python src/tools/<组>/<脚本>.py`；
- 生成物统一写 `build/`，不要写回 `src/`；
- 字体二进制不入库，见 `docs/字体与分发.md`。
