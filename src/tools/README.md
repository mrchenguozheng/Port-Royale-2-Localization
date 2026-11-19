# src/tools 脚本地图

脚本按用途分目录。这份地图要覆盖每一个脚本 —— `tools_check.py`（`check.py` 的一步）
会逐条核对：**每个 `.py` 都在这里出现，且都有模块 docstring**；写进来的路径也必须真的存在。

```
src/tools/
├─ pack/       编译、出包、批次、版本与补丁
├─ text/       归一化、中文/日文排版、标注、术语表、版本基线
├─ font/       字体生成、压缩与导出
├─ analysis/   译文检查、进度、说话人与语体分析
├─ install/    pr2ctl 构建/部署/启动/宿主 DLL
├─ translate.py / glossary.py / terms_check.py / placeholder_roles.py   译文数据层
├─ extract_strings.py                                                  从 PR2.exe 重提基准原文
├─ check.py / lint_imports.py / config_check.py / docs_check.py / tools_check.py   质量检查
└─ paths.py    公共路径
```

## 提交前入口

| 脚本 | 作用 |
|---|---|
| `check.py` | 跑全部检查与单测（`check.ps1` 调它）：跨模块引用 → 语言配置 → 译文规范 → 断行 → 微调层 → 不译清单 → 文档一致性 → 脚本地图 → 单测 |
| `lint_imports.py` | 找出「用了但没导入」的全局名 |
| `config_check.py` | locale/packs/translations/ui/font-map 的语言配置是否互相对得上；`release.ps1` 出包前也跑 |
| `docs_check.py` | 文档索引完整、编号唯一、生成物无漂移、窄断言 |
| `tools_check.py` | 本文件的完整性：每个脚本都被登记、都有 docstring；登记的路径确实存在 |
| `paths.py` | 公共路径常量（脚本按目录分组后统一从这里取仓库位置） |

## 基准与参考原文

| 脚本 | 作用 |
|---|---|
| `extract_strings.py` | 从 `PR2.exe` 的 PE 资源（`BINARY/167`）解出字符串表写成 toml，用于重建 `src/orig/*.toml` |
| `extract_retail_reference.py` | 把第三方零售语言包的 `strings.jsonl` 抽成 `src/orig` 参考原文（只做参考/QA，不出译文） |

## 译文数据层

| 脚本 | 作用 |
|---|---|
| `translate.py` | 译文唯一手改层的读写：合并、进度（`status`）、落盘（`apply`）、微调层自查（`overrides`） |
| `glossary.py` | 从现有译文生成「术语对照表」 |
| `terms_check.py` | 术语一致性：原文出现术语，译文有没有用约定译法 |
| `placeholder_roles.py` | 按 hash 记录「占位符之间的连接符」规则 |
| `pack/split_batches.py` | 按 en 表内顺序切可并行翻译的批次，落 `build/qa/batches/<语言>/` |
| `pack/merge_batches.py` | 批次译文合并回 TOML：占位符/标签校验、同文回填、失败自动还原 |
| `pack/quick.py` | 单条译文的快速修正路径 |

## 出包

| 脚本 | 作用 |
|---|---|
| `pack/compile_pack.py` | 译文 → 引擎语言包 `packs/<语言>.txt`（含 `--union` 并集基线、`--strict`、`--variant-out`） |
| `pack/build_artifacts.py` | 构建语言包产物的统一入口（编译 + 字体 + 清单） |
| `pack/make_release.py` | 按语言、按 GOG/Steam 入口生成发行 zip（`union=True`，两个 zip 共用同一份并集包） |
| `pack/release_manifest.py` | 生成并校验发行包根目录的 `manifest.json` |
| `pack/release_version.py` | 发行版本号与发行语言集的唯一口径 |
| `pack/build_time.py` | 「哪个时间」的唯一来源（可复现构建用） |
| `pack/pack_tags.py` | 语言包身份标记的唯一词表 |
| `pack/check_breaks.py` | 编译后核对译文与原文的换行（`<n>`）数量 |
| `pack/apply_patch.py` | 开发流程：校验 → 编译 → 部署到游戏目录一条命令（`apply_patch.ps1` 调它） |
| `pack/new_lang.py` | 命令行新建语言（只复制译文文件） |
| `pack/lang_add.py` | 加一门语言的骨架：译文/语言包/占位符/不译清单/语言规则/字体映射/断行跳过/两处 README，并实测原版字形覆盖 |

## 文本与规则

| 脚本 | 作用 |
|---|---|
| `text/normalize_text.py` | 按语言规则归一化标点（只改标点，不补排版空格） |
| `text/engine_text.py` | 译文 → 引擎文本的唯一构建入口（`--check/--stats/--diff`） |
| `text/entries.py` | 把译文条目按结构分类 |
| `text/marks.py` | 译文层内联标注：解析、展开、剥标 |
| `text/toml_io.py` | 译文与产物共用的 TOML 读写（id 顺序、转义、原子写） |
| `text/apply_zh_rules.py` | 中文构建入口的兼容门面，新代码用 `zh_pipeline` |
| `text/zh_pipeline.py` | 中文「分词前」：连词、人名、数字/破折号/`<n><n>` 空格 |
| `text/zh_space.py` | 中文分词与按字数成组补空格（spaCy → 机械兜底，不用 jieba） |
| `text/segment_zh.py` | `zh_space.py` 的分词子进程入口 |
| `text/space_stats.py` | 中文补空格预算的统计扫描（定 `MAX_CHARS` 用，历史工具） |
| `text/table_sync.py` | 术语表与译名表的骨架生成、跨语言同步、覆盖率报表 |
| `text/var_codes.py` | 文本变量码表 `@格式码$变量名$` 的事实源、生成与校验（`--sync` 重算码表与文档） |
| `text/verse_ans.py` | 诗谜谜底队列：把 `glossary/verse_ans.toml` 的 ans 落进各国译文 |
| `text/versions.py` | 版本基线（键集）与定向版本差（`baselines.toml` + `versions/*.toml`） |

语言规则（每门语言一份声明，`spec.py` 是接口）：

| 脚本 | 作用 |
|---|---|
| `text/lang_rules/spec.py` | 三段式接口：`Punctuation` / `Segmenter` / `Spacing` + `LangSpec` |
| `text/lang_rules/base.py` | 与语言无关的标点/占位符处理引擎 |
| `text/lang_rules/zh.py` | 中文：标点 + 分词器 + 补空格策略 |
| `text/lang_rules/ja.py` | 日文：标点 + 分词器 + 补空格策略 |
| `text/lang_rules/de.py` | 德文：显式 no-op（「不处理」是一份声明，不是缺失） |
| `text/lang_rules/es.py` | 西文：显式 no-op |
| `text/lang_rules/fr.py` | 法文：不补空格、不换空格、不引入任何特殊空白 |
| `text/lang_rules/ko.py` | 韩文：显式 no-op |
| `text/lang_rules/pl.py` | 波兰文：显式 no-op（字形覆盖待实机确认） |
| `text/lang_rules/ru.py` | 俄文：显式 no-op |

## 检查与分析

| 脚本 | 作用 |
|---|---|
| `analysis/text_lint.py` | 译文定则的可重跑检查（E/W 分级；占位符-助词、并列助词次序、版本差豁免等） |
| `analysis/keep_audit.py` | 「有意不译」清单对账：登记 id 存在、登记项没译过、结构性不可译的没占着待译 |
| `analysis/ref_check.py` | 参照版健康检查：照抄前先报「这批参照哪几条自身是坏的」（令牌/标签个数不齐、疑似截断） |
| `analysis/retail_import.py` | 零售参照导入：把参照文本落进译文，**顺带把 `[town:]`／`[term:]` 标注搬回原位**（按展开后的显示文本定位，找不到或出现多次就整行放弃）；结构缺陷交给 `apply` 拦（`--write` 才落盘，默认只出报告）；`--clean-ref` 先生成一版「小修小补的参考」（结构对齐基准、标点空白规整，token 仍只报不修） |
| `analysis/riddle_marks.py` | 诗谜标注搬运：从已核语言搬 `answer`／`group`／`level`／`certainty`／`source`，逐条核对本语言 `clue` 真的在谜面里；副本正文与代表不同会逐条点名 |
| `analysis/terms_seed.py` | 术语表取证起草：整行标签档直接成值，全库共现档按词干簇＋位置吻合＋密度比，不足只列候选（`--write` 落 `src/data/terms/<语言>.toml`） |
| `analysis/line_run.py` | 断行复核：断完最长一段有没有超上限（逐语言报告 `build/qa/line_run_*.txt`） |
| `analysis/lang_check.py` | 外语形态层：语法、拼写、复合词拆分（与 `text_lint` 分工：一个查形态，一个查定则） |
| `analysis/progress.py` | 翻译进度：已译 / 原样保留 / 还没动 |
| `analysis/speaker_audit.py` | 按「能不能判断说话人」给全部条目分级，只依据英/法原文 |
| `analysis/tone_proposal.py` | 生成「语体拟改清单」，只列能判定的 |
| `analysis/voice_match.py` | 语音转写匹配回语言包，得到「语音文件 ↔ hash」映射 |
| `analysis/debug_pack.py` | 生成可单独选中的排查语言包 `<lang>-debug.txt` |
| `analysis/align_export.py` | 把七语拉成对齐表（翻新语言时先查表） |
| `analysis/cpr_unpack.py` | `ASCARON_ARCHIVE V0.9`（`.cpr`）解包，只读、不依赖第三方库 |
| `analysis/lua_missions.py` | 从 `luac -l` 反汇编清单读任务注册表（`missions.bin` 是改过的 Lua 4.1 字节码） |
| `analysis/de_lint.py` | 德语确定性校验（`--md` 默认写 `docs/archive/德语校对清单.md`） |
| `analysis/de_index.py` | 德语文案条目索引（英/德/法/零售四线对照） |
| `analysis/de_crosscheck.py` | 德语交叉核对：英文基准、零售德语、同版法语三条线查问题 |
| `analysis/de_apply.py` | 按 key 整行替换 `de.toml` 译文（一次性批次工具） |
| `analysis/de_econ.py` | 德语经济档位口径统一（一次性批次工具） |
| `analysis/de_fix.py` | 德语交叉核对查出的硬错修补（一次性批次工具） |
| `analysis/de_register.py` | 德语口语语体回补（一次性批次工具） |
| `analysis/de_riddles.py` | 德语藏宝诗谜重译（押韵，一次性批次工具） |
| `analysis/de_riddles2.py` | 德语诗谜二轮打磨（一次性批次工具） |

## 字体

| 脚本 | 作用 |
|---|---|
| `font/make_noto_fonts.py` | 生成 Noto 替换字体（字体只做映射，不做裁剪） |
| `font/build_cyr_fonts.py` | 俄语四个自建字体（正文 + 标题三档） |
| `font/build_lat_fonts.py` | 拉丁扩展 A 语言（pl）的三个标题字体：正文原版够用，只换标题槽位 |
| `font/squeeze_fonts.py` | TrueType（glyf）水平压缩，按原版度量调，供日文等宽字符用 |
| `font/extract_fonts.py` | 从 `pr2_loca.cpr` 导出原版拉丁字体（只用于测度量） |

## 安装与运行

| 脚本 | 作用 |
|---|---|
| `install/pr2ctl/base.py` | 路径常量、已知版本、补丁清单与文件小工具 |
| `install/pr2ctl/build.py` | 调 cargo 构建注入器、编译语言包 |
| `install/pr2ctl/deploy.py` | 把构建产物复制进游戏目录 |
| `install/pr2ctl/detect.py` | 版本识别、补丁状态、语言包盘点 |
| `install/pr2ctl/launch.py` | 启动游戏与原版对比 |
| `install/pr2ctl/settings.py` | 记住游戏目录与上次选择 |
| `install/pr2ctl/steam_host.py` | Steam 版宿主 DLL 的备份、挂载与还原 |

## 约定

- 各组脚本把 `src/tools` 加进 `sys.path`，共享模块（`translate.py` 等）仍在根目录；
- 组内脚本用 `python src/tools/<组>/<脚本>.py` 运行；
- 生成物统一写 `build/`，不写回 `src/`；
- 一次性批次脚本（德语那几个 `de_apply`/`de_fix`/`de_econ`/`de_register`/`de_riddles*`）
  写完数据就留在仓库里当依据，**不再重跑**；对应的批次记录在 `docs/archive/`；
- 新增脚本要同时改这份地图，否则 `tools_check.py` 在 `check.py` 里报错。
