# src/tools 脚本地图

脚本很多，按用途分组。日常只需要记住最上面“常用入口”。

## 常用入口

| 脚本 | 作用 |
|---|---|
| `apply_patch.py` | 归一化 → 校验 → 编译 → 部署，一条命令跑完（`apply_patch.bat` 调它） |
| `check.py` | 跑全部静态检查与单测（`check.bat` 调它） |
| `new_lang.py` | 命令行新建语言（编辑器里也能建） |
| `compile_pack.py` | 把 `src/live/*.toml` 编译成 `build/PR2Packs/*.txt` |
| `check_breaks.py` | 编译后校验换行/占位符 |

## 文本规则

| 脚本 | 作用 |
|---|---|
| `normalize_text.py` | 按语言规则归一化标点、空格 |
| `apply_zh_rules.py` / `apply_ja_rules.py` | 中文/日文规则管线（空格、名字、断行） |
| `lang_rules/` | 各语言规则模块 |
| `segment_zh.py` / `zh_dep_space.py` / `space_words.py` | 中文分词与空格实验 |
| `zh_names.txt` / `zh_towns.txt` / `zh_userdict.txt` | 人名、地名、分词词典 |

## 翻译与术语

| 脚本 | 作用 |
|---|---|
| `translate.py` | 调模型批量翻译 |
| `glossary.py` | 术语表读取/应用 |
| `terms_check.py` | 术语一致性检查 |
| `placeholder_roles.py` | 占位符语义与角色 |
| `speaker_audit.py` / `tone_proposal.py` / `voice_match.py` | 说话人、语气、称谓分析 |

## 字体

| 路径 | 作用 |
|---|---|
| `subset_fonts.py` | 字体缝合入口（按 presets 的语言配置） |
| `extract_fonts.py` | 从游戏 `pr2_loca.cpr` 导出原版拉丁字体 |
| `fontstitch/` | 缝合引擎、donor presets、校验工具 |

字体前置检查：

```bash
python src/tools/subset_fonts.py --check
```

## 构建、安装与诊断

| 路径 | 作用 |
|---|---|
| `pr2ctl/` | 构建/部署/启动的共享实现 |
| `server_status.py` | 探测本机编辑器实例 |
| `progress.py` | 进度显示 |
| `width_check.py` | 用字体宽度粗查译文是否超宽 |
| `lint_imports.py` | 跨模块引用检查 |

## 数据文件

| 文件 | 内容 |
|---|---|
| `zh_names.txt` | 中文人名/地名匹配表 |
| `zh_towns.txt` | 城镇名 |
| `zh_userdict.txt` | 分词用户词典 |

## 约定

- 脚本之间通过 `sys.path` 同目录导入，移动文件时要同步改引用；
- 生成物统一写 `build/`，不要写回 `src/`；
- 字体二进制不入库，见 `docs/字体与分发.md`。
