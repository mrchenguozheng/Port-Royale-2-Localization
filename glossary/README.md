# 术语对照表

游戏里的专有名词（货物、船只、军衔、城镇……）散在三千多条文本里，翻译时
最容易前后不一致：同一个 "Frigate" 这封信用「巡防舰」、下封信变成「护卫舰」。
这个文件夹把它们按组抽出来，**英文、中文、法语并排**，既是翻译时的参考，
也是校对清单。

## 目录里只放「源」

| 文件 | 说明 |
|---|---|
| `terms.toml` | 术语清单：**哪些字符串算术语、归到哪一组**。唯一需要手工维护的文件 |
| `README.md` | 本文件 |

**生成物不进仓库**（`build/` 已在 .gitignore 里）：

| 生成物 | 说明 |
|---|---|
| `build\glossary\zh.md` | 中文对照表（含法语对照列） |
| `build\glossary\zh.csv` | 同上的 CSV（UTF-8 BOM，Excel 直接打开不乱码） |
| `build\glossary\<语言>.md` | 以后加语言时自动出现 |

理由：表是从 `terms.toml` + `translations\` 现算出来的，改了译文重跑一次
就同步；提交进 git 只会多一份必然过期的副本，还会让每次改译文都多出一堆
diff。它和语言包、字体一样属于「产物」。

## 重新生成

```bat
python src\tools\glossary.py                 :: 中文表（自动带法语对照列）
python src\tools\glossary.py --csv           :: 另外导出 csv
python src\tools\glossary.py --with fr.gog_1.1.2.42   :: 指定对照语言
python src\tools\glossary.py --out D:\out    :: 换个输出目录
```

「构建所选语言」时也会顺带重新生成一次，所以正常流程里不用单独跑。

表里的译文是**从 `src\translations\` 现取的**，不是抄在术语文件里的，所以
不用维护两份。

## 多义词：May / Jan 这些

英文里有些词既可能是月份，也可能是人名、船名：

- `Jan` 一条是「1月」，另一条是人名「扬」；
- `May` 一条是「五月」，另一条是日期缩写里的「5月」；
- `Load` 一条是「读取（存档）」，另外几条是「装载（装货）」。

所以术语表**按 id 认条目**，不按英文认；同时生成时会在每组后面附一段
**同名条目**，把「英文相同、译文却不一样」的其它条目列出来 —— 看到
`May` 时就知道它还有别的意思，别当成月份去套。

## 术语清单怎么写

`terms.toml` 里每组一个 `[[group]]`：

```toml
[[group]]
name = "货物"
note = "市场里买卖的商品"          # 可选，生成后作为该组说明
range = ["0x37328fb9", "0x37329033"]  # 取这个 id 区间内的条目
max_len = 24                          # 可选：挡掉区间里夹着的长句子

[[group]]
name = "国家"
ids = ["0xf90d7ea2", "0xf90d7ea3", "0xf90d7ea5"]   # 零散分布的用 ids 精确列
```

游戏字符串表里同类条目常常连续排列（货物、船只、军衔、城镇都是），所以
`range` 比一条条列 id 好维护；零散的那些再用 `ids`。

**id 怎么找**：编辑器里选中条目会显示 id；或者用
`python src\tools\translate.py --help` 里的搜索命令。

## 以后加别的语言

1. 在 `src\translations\` 放好 `<语言>.toml`（编辑器里「＋ 添加语言」即可）；
2. 跑一次 `python src\tools\glossary.py --lang <语言>`，生成 `build\glossary\<语言>.md`；
3. `terms.toml` 一个字都不用动 —— 术语是按 id 认的，跟语言无关；
4. 想让它显示成「法语」而不是代码，在 `src\tools\glossary.py` 的
   `LANG_NAMES` 里补一行。

参考语言（`references\` 里的法文原本）也能导出：

```bat
python src\tools\glossary.py --lang fr.gog_1.1.2.42
```

## 已知的不一致（术语表把它们摊开了）

- 「五月」有两条：`0x327c63bf` = 五月（月份名）、`0x0247d1b7` = 5月（日期缩写）；
- 其余月份也是「一月 / 1月」两套，日期串用的是后者；
- `Jan` 的人名条目译作「扬」，与月份「1月」不同源，别混用。

## 自动检查：术语一致性

光有一张表还得靠人记；所以另有一个脚本把术语表当**规则**用：

```bat
python src\tools\terms_check.py            :: 查所有可编辑语言
python src\tools\terms_check.py --lang zh
python src\tools\terms_check.py --json     :: 给编辑器/脚本用
python src\tools\terms_check.py --strict   :: 有问题时退出码 1（可进 CI）
```

规则是「原文里出现 `Frigate`，译文里就该出现「巡防舰」」：

- 整词匹配（`Frigate` 不会命中 `Frigatebird`），首字母大写时区分大小写
  （否则 `may` 这个情态动词会被当成五月）；
- 复数只认 `s`（不认 `es`，否则 `Wood` 会命中人名 `Woodes Rogers`）；
- 长词优先：`Rear Admiral` 命中后，里面的 `Admiral` 不再重复报；
- 译文比较**忽略空格**（「6 月」和「6月」同义）；
- 译文里包含约定译法即通过（「军事巡防舰」含「巡防舰」）。

可以在 `terms.toml` 里微调：

```toml
# 整组不查：界面词一词多义，不适合自动判
[[group]]
name = "界面"
check = false

# 同一个词允许的另一种译法（按术语条目的 id）
[group.alt]
"0xdc939a60" = ["教会"]      # Catholic Church → 教会

# 与术语无关的误命中，整条跳过
ignore = ["0xfc512ea5"]       # 版权声明里的 RAD Game Tools
```

**编辑器里也接了**：打开编辑器时会自动跑一次，右上角状态显示
「术语待统一 N 条」，对应行下面用橙色标出「Turk Islands：应为「特克群岛」」。
