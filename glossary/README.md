# 术语对照表

游戏里的专有名词（货物、船只、军衔、城镇……）散在三千多条文本里，翻译时
最容易前后不一致：同一个 "Frigate" 这封信用「巡防舰」、下封信变成「护卫舰」。
这个文件夹把它们按组抽出来，**英文与译文并排**，既是翻译时的参考，也是校对
清单。

## 目录里有什么

| 文件 | 说明 |
|---|---|
| `terms.toml` | 术语清单：**哪些字符串算术语、归到哪一组**。唯一需要手工维护的文件 |
| `zh.md` | 中文对照表（生成物，别手改） |
| `zh.csv` | 同上的 CSV（UTF-8 BOM，Excel 直接打开不乱码） |
| `<语言>.md` | 以后加语言时自动出现，例如 `fr.md` |

## 重新生成

改了译文、或往 `terms.toml` 加了术语之后：

```bat
python src\tools\glossary.py            :: 所有可编辑语言
python src\tools\glossary.py --lang zh  :: 只做中文
python src\tools\glossary.py --csv      :: 另外导出 csv
```

表里的译文是**从 `src\translations\` 现取的**，不是抄在术语文件里的，所以
不用维护两份；`zh.md` 是生成物，手改会在下次生成时被覆盖。

## 术语清单怎么写

`terms.toml` 里每组一个 `[[group]]`：

```toml
[[group]]
name = "货物"
note = "市场里买卖的商品"          # 可选，生成后会作为该组的说明
range = ["0x37328fb9", "0x37329033"]  # 取这个 id 区间内的条目
max_len = 24                          # 可选：挡掉区间里夹着的长句子

[[group]]
name = "国家"
ids = ["0xf90d7ea2", "0xf90d7ea3", "0xf90d7ea5"]   # 零散分布的用 ids 精确列
```

游戏字符串表里同类条目常常连续排列（货物、船只、军衔、城镇都是），所以
`range` 比一条条列 id 好维护；零散的那些再用 `ids`。

**id 怎么找**：编辑器里选中条目会显示 id；或者 `python src\tools\translate.py
search --query "Frigate"`。

## 以后加别的语言

1. 在 `src\translations\` 放好 `<语言>.toml`（编辑器里「＋ 添加语言」即可）；
2. 跑一次 `python src\tools\glossary.py --lang <语言>`，就会生成 `glossary\<语言>.md`；
3. `terms.toml` 一个字都不用动 —— 术语是按 id 认的，跟语言无关；
4. 想让它显示成「法语」而不是 `fr`，在 `src\tools\glossary.py` 的 `LANG_NAMES`
   里补一行。

参考语言（`references\` 里的法文原本）也能导出：

```bat
python src\tools\glossary.py --lang fr.gog_1.1.2.42
```

## 已知的不一致

术语表把问题摊开之后，有几处值得顺手统一（改译文，不改术语文件）：

- 「五月」有两条：`0x327c63bf` = 五月、`0x0247d1b7`（英文 May） = 5月；
- 其余月份也有两类写法（一月 / 1月），日期串用的是后者；
- `Load` 有「装载（装货）」和「读取（存档）」两种意思，术语表里取后者。
